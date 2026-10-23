"""Synthetic certificate tests; never represent real matrix/runtime acceptance."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from integration.ui_matrix import completion as c, completion_producers as p, evidence_scope as s
from tests.review_tools.injection_predicates import eligible, expected_from

class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir()
        (self.source/'upstream.lock.json').write_text('{}')
        self.evidence=self.root/'evidence';self.evidence.mkdir()
        self.env=patch.dict(os.environ);self.env.start();self.addCleanup(self.env.stop)
        os.environ.pop('BRIDGE_MATRIX_RUN_ID',None)
        self.scope=s.start_run(self.source,self.evidence)
        os.environ['BRIDGE_MATRIX_RUN_ID']=self.scope['runId']
        self.folder=self.evidence/'runs'/self.scope['runId']
    def write(self,name,value): c.atomic_once(self.folder,name,value)
    def execute_report(self,stage):
        rows=[{'id':i,'result':'CONFIG_PASS','restored':True} for i in p.stage_cases(stage)]
        self.write(p.REPORTS[stage],rows)
        summary=p.execution_summary(stage,self.folder)
        self.write('executed-'+stage+'.json',dict(summary,scope=self.scope,stage=stage,
            returncode=0,completed=True,reports=[c.reference(self.folder,p.REPORTS[stage])]))
    def produce(self,name):return p.produce(name,root=self.source,evidence=self.evidence)
    def read(self,name):return c.read(name,root=self.source,evidence=self.evidence)
    def baseline(self):self.execute_report('baseline');self.produce('baseline-ready')
    def test_five_real_producer_entrypoints_with_synthetic_reports_only(self):
        self.baseline();self.execute_report('continue_nodes');self.produce('nodes-complete')
        for stage in ('continue_metadata','continue_subscription'):self.execute_report(stage)
        self.produce('metadata-subscription-complete');self.execute_report('path_environment')
        self.write('path-cleanup-verified.json',{'cleanupVerified':True})
        self.produce('paths-complete')
        for stage in ('continue_global','extension_profile_probe','continue_dns'):self.execute_report(stage)
        self.produce('queue-complete')
        for name in c.PREDECESSORS:self.assertTrue(self.read(name)['acceptancePassed'])
    def test_actual_single_object_report_shape(self):
        stage='extension_profile_probe'
        self.write(p.REPORTS[stage],{'id':p.stage_cases(stage)[0],
            'result':'RUNTIME_PASS','baselineRestored':True})
        summary=p.execution_summary(stage,self.folder)
        self.assertTrue(summary['classificationComplete'])
        # A top-level row is an actual row witness, not a queue receipt.
        row={'id':p.stage_cases(stage)[0],'result':'RUNTIME_PASS','restored':True,
             'witness':dict(c.reference(self.folder,p.REPORTS[stage]),pointer='')}
        c.verify_rows(self.folder,p.stage_cases(stage),[row])
    def test_path_environment_uses_certificate_before_network(self):
        import ast
        source=(Path(__file__).resolve().parents[2]/'integration/ui_matrix/path_environment.py').read_text()
        tree=ast.parse(source);main=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='main')
        # Run the unchanged function, with unavailable certificate; no network
        # operation may be reached and an empty file cannot satisfy the gate.
        def denied(name):
            self.assertEqual(name,'metadata-subscription-complete')
            raise RuntimeError('CERTIFICATE_REQUIRED')
        def network(*a):raise AssertionError('NETWORK_BEFORE_CERTIFICATE')
        ns={'__name__':'_real_path_environment','__file__':str(Path(__file__).resolve()),
            'Path':Path,'scope_file':lambda _:self.folder,'read_completion':denied,
            'need':s.require,'command':network}
        exec(compile(ast.Module(body=[main],type_ignores=[]),'<path_environment>','exec'),ns)
        (self.folder/'metadata-subscription-complete').write_text('')
        with self.assertRaisesRegex(RuntimeError,'CERTIFICATE_REQUIRED'):ns['main']()
    def test_empty_marker_not_accepted(self):
        (self.folder/'baseline-ready').write_text('')
        with self.assertRaises((ValueError,RuntimeError)):self.read('baseline-ready')
    def test_missing_case_refused(self):
        rows=[{'id':'health','result':'CONFIG_PASS','restored':True}]
        self.write(p.REPORTS['baseline'],rows)
        self.assertFalse(p.execution_summary('baseline',self.folder)['classificationComplete'])
    def test_null_result_refused(self):
        self.write(p.REPORTS['baseline'],[{'id':i,'result':None,'restored':True} for i in p.stage_cases('baseline')])
        self.assertFalse(p.execution_summary('baseline',self.folder)['classificationComplete'])
    def test_unrestored_refused(self):
        self.write(p.REPORTS['baseline'],[{'id':i,'result':'CONFIG_PASS','restored':False} for i in p.stage_cases('baseline')])
        self.assertFalse(p.execution_summary('baseline',self.folder)['baselineRestored'])
    def test_nonzero_execution_refused(self):
        self.execute_report('baseline');path=self.folder/'executed-baseline.json';v=json.loads(path.read_text());v['returncode']=9;path.write_text(json.dumps(v))
        with self.assertRaisesRegex(RuntimeError,'EXECUTION_FAILED'):self.produce('baseline-ready')
    def test_report_changed_refused(self):
        self.baseline();(self.folder/p.REPORTS['baseline']).write_text('[]')
        with self.assertRaisesRegex(RuntimeError,'HASH_CHANGED'):self.read('baseline-ready')
    def test_source_changed_refused(self):
        self.baseline();(self.source/'install.sh').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'CONTEXT_CHANGED'):self.read('baseline-ready')
    def test_fake_self_selected_plan_refused(self):
        self.baseline();path=self.folder/'baseline-ready';v=json.loads(path.read_text());v['requiredCases']=['health'];v['planSha256']=s.sha(c.encoded(v['requiredCases']));path.write_text(json.dumps(v))
        with self.assertRaisesRegex(RuntimeError,'PLAN_CHANGED'):self.read('baseline-ready')
    def test_duplicate_publication_refused(self):
        self.baseline()
        with self.assertRaises(FileExistsError):self.produce('baseline-ready')
    def test_symlink_report_refused(self):
        (self.folder/'bad.json').symlink_to(self.source/'upstream.lock.json')
        with self.assertRaises((RuntimeError,OSError)):c.load(self.folder,'bad.json')
    def test_traversal_report_refused(self):
        with self.assertRaises(RuntimeError):c.load(self.folder,'../source/upstream.lock.json')
    def test_upstream_failure_preserved_as_failure(self):
        rows=[{'id':i,'result':'CONFIG_PASS','restored':True} for i in p.stage_cases('baseline')]
        rows[0].update(result='FAIL',owner='official DAE',reason='Synthetic test finding',sourceEvidence='synthetic fixture source')
        self.write(p.REPORTS['baseline'],rows)
        summary=p.execution_summary('baseline',self.folder)
        self.assertTrue(summary['classificationComplete']);self.assertFalse(summary['acceptancePassed'])
        self.write('executed-baseline.json',dict(summary,scope=self.scope,stage='baseline',returncode=0,completed=True,reports=[c.reference(self.folder,p.REPORTS['baseline'])]))
        self.assertFalse(self.produce('baseline-ready')['acceptancePassed'])
    def test_unreviewed_fixture_failure_not_classified(self):
        self.write(p.REPORTS['baseline'],[{'id':i,'result':'FAIL','restored':True,'reason':'fixture exception'} for i in p.stage_cases('baseline')])
        self.assertFalse(p.execution_summary('baseline',self.folder)['classificationComplete'])

class InjectionTests(unittest.TestCase):
    def test_shared_constructor_matches_real_observer_contract(self):
        before={'native':{'attemptId':'old'},'install':{'generation':'g'},'manifest':'sha'}
        expected=expected_from(before)
        o={'native':{'attemptId':'new','phase':'QUIESCING','recoveryScope':'triggers-only','beforeTimers':{'x':{'ActiveState':'active'}},'previousGeneration':'g'},'install':{'generation':'g','phase':'COMMITTED'},'manifest':'sha','processMatches':True,'ownsReleaseLock':True,'timers':{'x':{'ActiveState':'inactive'}}}
        self.assertTrue(eligible(o,expected)[0])
        for key in ('phase','recoveryScope','attemptId','previousGeneration'):
            bad=copy.deepcopy(o);bad['native'][key]='old' if key=='attemptId' else 'wrong'
            self.assertFalse(eligible(bad,expected)[0])
        for key in ('processMatches','ownsReleaseLock'):
            bad=copy.deepcopy(o);bad[key]=False;self.assertFalse(eligible(bad,expected)[0])
    def test_wrong_generation_type_refused(self):
        with self.assertRaises(ValueError):expected_from({'native':{'attemptId':'old'},'install':{'generation':12},'manifest':'sha'})

if __name__=='__main__':unittest.main()


class NodeClassificationTests(unittest.TestCase):
    def test_config_chain_is_not_runtime(self):
        from integration.ui_matrix.continue_nodes import config_classification
        row=config_classification({'sourceIgnored':[]})
        self.assertEqual(row['result'],'CONFIG_PASS')
        self.assertEqual(row['runtimeEvidence'],'NOT_CLAIMED_CONFIG_CHAIN_ONLY')
    def test_existing_source_findings_remain_fail(self):
        from integration.ui_matrix.continue_nodes import cases,config_classification
        for case in cases():
            if case['sourceIgnored']:
                row=config_classification(case)
                self.assertEqual(row['result'],'FAIL')
                self.assertEqual(row['owner'],'official daed' if case['id']=='vless-xhttp' else 'official DAE')
                self.assertEqual(len(row['sourceEvidence']['sections']),len(case['sourceIgnored']))
    def test_unknown_source_finding_rejected(self):
        from integration.ui_matrix.continue_nodes import config_classification
        with self.assertRaisesRegex(RuntimeError,'PINNED_IGNORED_FIELD_EVIDENCE_MISSING'):
            config_classification({'sourceIgnored':['invented.field']})


class ImportRejectionClassificationTests(unittest.TestCase):
    def setUp(self):
        from integration.ui_matrix.continue_nodes import cases
        self.case=next(c for c in cases() if c['id']=='vless-xhttp')
        self.error=RuntimeError('GRAPHQL_REJECTED:["create vle[REDACTED_URI] unexpected field: network: xhttp"]')
    def classify(self, case=None, stage='import', error=None):
        from integration.ui_matrix.continue_nodes import import_rejection_classification
        return import_rejection_classification(case or self.case,stage,error or self.error)
    def test_exact_rejection_retains_failure_and_source(self):
        result=self.classify()
        self.assertEqual(result['owner'],'official daed')
        self.assertNotIn('result',result)
        self.assertNotIn('acceptancePassed',result)
        self.assertEqual(result['sourceEvidence']['observedError'],str(self.error))
    def test_unknown_errors_and_wrong_stage_not_classified(self):
        for error in (RuntimeError('GRAPHQL_REJECTED:["access denied"]'),ValueError(str(self.error))):
            self.assertEqual(self.classify(error=error),{})
        self.assertEqual(self.classify(stage='validate-apply'),{})
        wrong=dict(self.case,id='other')
        self.assertEqual(self.classify(case=wrong),{})
    def test_missing_source_evidence_rejected(self):
        from unittest.mock import patch
        with patch('integration.ui_matrix.continue_nodes.config_classification',side_effect=RuntimeError('PINNED_IGNORED_FIELD_EVIDENCE_MISSING')):
            with self.assertRaisesRegex(RuntimeError,'EVIDENCE_MISSING'):self.classify()
    def test_restoration_failure_still_rejected(self):
        from integration.ui_matrix.completion_producers import classified
        row=dict(self.classify(),id='vless-xhttp',result='FAIL',reason=str(self.error),witness={})
        with self.assertRaisesRegex(RuntimeError,'BASELINE_NOT_RESTORED'):classified(row)
        row['baselineRestored']=True
        self.assertEqual(classified(row)['result'],'FAIL')
