"""Real offline report CLI with synthetic run files, not network evidence."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from integration.ui_matrix import evidence_scope as scope, evidence_report as report

class ScopedReporterTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);root=Path(t.name).resolve()
        self.source=root/'source';self.source.mkdir();(self.source/'upstream.lock.json').write_text('{}')
        self.evidence=root/'evidence';self.evidence.mkdir()
        self.binding=scope.start_run(self.source,self.evidence,boot='synthetic-offline-run')
        self.folder=self.evidence/'runs'/self.binding['runId']
        self.catalogue={'controls':[{'id':'sample','category':'DATA_PLANE_SETTING','graphql':'synthetic','daeOrEffect':'synthetic'}]}
        raw=b'{"value":true}\n';(self.folder/'observation.json').write_bytes(raw)
        self.ledger=[{'control':'sample','result':'CONFIG_PASS','file':'observation.json',
                      'pointer':'/value','expected':True,'sha256':hashlib.sha256(raw).hexdigest(),
                      'reason':'synthetic unit test only','chain':{k:'NOT_PROVEN' for k in report.CHAIN}}]
        (self.folder/'catalogue.json').write_text(json.dumps(self.catalogue))
        self.save_ledger()
    def save_ledger(self):(self.folder/'ledger.json').write_text(json.dumps(self.ledger))
    def invoke(self, output='report'):
        args=['evidence_report','catalogue.json','ledger.json',str(self.folder),output,'--source-root',str(self.source)]
        with patch.object(sys,'argv',args),redirect_stdout(io.StringIO()):report.main()
    def test_cli_attaches_exact_scope(self):
        self.invoke();value=json.loads((self.folder/'report.json').read_text())
        self.assertEqual(value['evidenceScope'],self.binding)
        self.assertEqual(value['controls'][0]['result'],'CONFIG_PASS')
        self.assertEqual(value['controls'][0]['chain']['runtime'],'NOT_PROVEN')
        self.assertTrue((self.folder/'report.md').is_file())
    def test_missing_scope_rejects_before_report_write(self):
        (self.folder/'scope.json').unlink()
        with self.assertRaises(OSError):self.invoke()
        self.assertFalse((self.folder/'report.json').exists())
    def test_deployment_only_source_drift_rejects_report(self):
        (self.source/'deployment').mkdir();(self.source/'deployment/a.service').write_text('new')
        with self.assertRaisesRegex(RuntimeError,'REPORT_SOURCE_CHANGED'):self.invoke()
    def test_ledger_cannot_consume_previous_run_by_traversal(self):
        self.ledger[0]['file']='../old.json';self.save_ledger()
        with self.assertRaisesRegex(RuntimeError,'EVIDENCE_PATH'):self.invoke()
    def test_output_cannot_overwrite_ledger(self):
        original=(self.folder/'ledger.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'OVERLAPS'):self.invoke('ledger')
        self.assertEqual((self.folder/'ledger.json').read_bytes(),original)
    def test_output_cannot_overwrite_input_evidence(self):
        with self.assertRaisesRegex(ValueError,'OVERLAPS'):self.invoke('observation')
    def test_output_cannot_escape_run(self):
        with self.assertRaises(RuntimeError):self.invoke('../report')
    def test_hash_failure_still_rejects_evidence(self):
        (self.folder/'observation.json').write_text('{"value":false}')
        with self.assertRaisesRegex(ValueError,'EVIDENCE_HASH_CHANGED'):self.invoke()
    def test_scope_is_rechecked_after_build(self):
        original=report.build
        def change(*args):
            value=original(*args);(self.source/'upgrade.sh').write_text('changed');return value
        with patch.object(report,'build',side_effect=change),self.assertRaisesRegex(RuntimeError,'REPORT_SOURCE_CHANGED'):
            self.invoke()
        self.assertFalse((self.folder/'report.json').exists())
    def test_aggregate_build_rejects_absolute_evidence_file(self):
        self.ledger[0]['file']=str(self.folder/'observation.json')
        with self.assertRaises(RuntimeError):report.build(self.catalogue,self.ledger,self.folder)

if __name__=='__main__':unittest.main(verbosity=2)
