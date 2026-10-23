"""R4 evidence path and launcher chain tests; no network/service operation."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from integration.ui_matrix import evidence_scope as scope, evidence_report as report
from integration.ui_matrix import run_scope


class ScopeChainTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.source=self.root/'source';self.source.mkdir()
        (self.source/'upstream.lock.json').write_text('{}')
        self.evidence=self.root/'evidence';self.evidence.mkdir()
        self.env=patch.dict(os.environ);self.env.start();self.addCleanup(self.env.stop)
        os.environ.pop('BRIDGE_MATRIX_RUN_ID',None)
        self.binding=scope.start_run(self.source,self.evidence)
        self.folder=self.evidence/'runs'/self.binding['runId']
    def path(self,name):
        return scope.scope_file(self.evidence/name,root=self.source,evidence=self.evidence)
    def activate(self):os.environ['BRIDGE_MATRIX_RUN_ID']=self.binding['runId']
    def test_unpinned_runtime_cannot_implicitly_use_latest_run(self):
        with self.assertRaisesRegex(RuntimeError,'ID_REQUIRED'):self.path('result.json')
    def test_pinned_runtime_reads_only_its_namespace(self):
        self.activate();(self.evidence/'old-marker').write_text('old')
        self.assertFalse(self.path('old-marker').exists())
        self.assertEqual(self.path('new'),self.folder/'new')
    def test_pointer_switch_does_not_move_an_old_process(self):
        self.activate();scope.start_run(self.source,self.evidence)
        with self.assertRaisesRegex(RuntimeError,'RUN_REPLACED'):self.path('new')
    def test_active_launcher_prevents_new_run_initialization(self):
        with scope.run_lock(self.evidence):
            with self.assertRaisesRegex(RuntimeError,'BUSY'):scope.start_run(self.source,self.evidence)
    def test_symlink_output_rejected(self):
        self.activate();(self.folder/'link').symlink_to(self.source/'upstream.lock.json')
        with self.assertRaisesRegex(RuntimeError,'EVIDENCE_LINK'):self.path('link')
    def test_scoped_root_cannot_be_scoped_twice(self):
        self.activate()
        with self.assertRaisesRegex(RuntimeError,'EVIDENCE_PATH'):
            scope.scope_file(self.folder/'x',root=self.source,evidence=self.evidence)
    def test_launcher_preserves_optimize_and_pin(self):
        runner=Mock(return_value=types.SimpleNamespace(returncode=7))
        result=run_scope.execute('continue_global',[],self.binding['runId'],source=self.source,evidence=self.evidence,runner=runner)
        self.assertEqual(result,7)
        self.assertEqual(runner.call_args.kwargs['env']['PYTHONOPTIMIZE'],str(sys.flags.optimize))
        self.assertEqual(runner.call_args.kwargs['env']['BRIDGE_MATRIX_RUN_ID'],self.binding['runId'])
        self.assertFalse(runner.call_args.kwargs['check'])
    def test_unknown_stage_not_executed(self):
        runner=Mock()
        with self.assertRaisesRegex(RuntimeError,'NOT_ALLOWED'):
            run_scope.execute('os',[],self.binding['runId'],source=self.source,evidence=self.evidence,runner=runner)
        runner.assert_not_called()
    def test_wrong_explicit_run_is_rejected_before_child(self):
        runner=Mock()
        with self.assertRaisesRegex(RuntimeError,'RUN_REPLACED'):
            run_scope.execute('continue_global',[],'f'*32,source=self.source,evidence=self.evidence,runner=runner)
        runner.assert_not_called()
    def test_child_source_change_is_not_accepted(self):
        def child(*a,**kw):
            (self.source/'upgrade.sh').write_text('changed')
            return types.SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(RuntimeError,'CONTEXT_CHANGED'):
            run_scope.execute('continue_global',[],self.binding['runId'],source=self.source,evidence=self.evidence,runner=child)
    def test_child_holds_lock_even_on_failure(self):
        def child(*a,**kw):
            with self.assertRaisesRegex(RuntimeError,'BUSY'):scope.start_run(self.source,self.evidence)
            raise OSError('child failed')
        with self.assertRaises(OSError):
            run_scope.execute('continue_global',[],self.binding['runId'],source=self.source,evidence=self.evidence,runner=child)
        scope.start_run(self.source,self.evidence)  # lock was closed
    def test_real_child_environment_and_report_are_bound_to_same_run(self):
        # A real subprocess creates only synthetic evidence. The real launcher
        # supplies its environment; this is not the real matrix/network stage.
        def child(command,**kw):
            program="import json,os,pathlib; p=pathlib.Path(os.environ['OUTPUT']); p.write_text(json.dumps({'run':os.environ['BRIDGE_MATRIX_RUN_ID'],'value':True}))"
            kw['env']=dict(kw['env'],OUTPUT=str(self.folder/'observation.json'))
            return subprocess.run([sys.executable,'-B','-c',program],**kw)
        self.assertEqual(run_scope.execute('continue_global',[],self.binding['runId'],source=self.source,evidence=self.evidence,runner=child),0)
        raw=(self.folder/'observation.json').read_bytes()
        self.assertEqual(json.loads(raw)['run'],self.binding['runId'])
        cat={'controls':[{'id':'scope-witness','category':'DATA_PLANE_SETTING','graphql':'synthetic','daeOrEffect':'synthetic'}]}
        ledger=[{'control':'scope-witness','result':'CONFIG_PASS','file':'observation.json','pointer':'/value','expected':True,
                 'sha256':hashlib.sha256(raw).hexdigest(),'reason':'Synthetic evidence chain only',
                 'chain':{k:'NOT_PROVEN' for k in report.CHAIN}}]
        (self.folder/'catalogue.json').write_text(json.dumps(cat));(self.folder/'ledger.json').write_text(json.dumps(ledger))
        args=['report','catalogue.json','ledger.json',str(self.folder),'result','--source-root',str(self.source)]
        with patch.object(sys,'argv',args),redirect_stdout(io.StringIO()):report.main()
        result=json.loads((self.folder/'result.json').read_text())
        self.assertEqual(result['evidenceScope'],self.binding)
        self.assertEqual(result['controls'][0]['chain']['runtime'],'NOT_PROVEN')
        (self.source/'deployment').mkdir();(self.source/'deployment/test.service').write_text('changed')
        with patch.object(sys,'argv',args),self.assertRaisesRegex(RuntimeError,'REPORT_SOURCE_CHANGED'):report.main()
    def test_invalid_lock_link_refused(self):
        (self.evidence/'.matrix-run.lock').unlink()
        (self.evidence/'.matrix-run.lock').symlink_to(self.source/'upstream.lock.json')
        with self.assertRaises(OSError):
            with scope.run_lock(self.evidence):self.fail('unsafe lock accepted')

if __name__=='__main__':unittest.main()
