"""Isolated projection tests. Stubs represent already-existing runtime contracts.

These exercise the new module, NOT the real collector/DAE, systemd or production.
"""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]

class FakeStore:
    def __init__(self, runtime):self.r=runtime
    def load(self):return self.r.generation, copy.deepcopy(self.r.saved)
    def commit(self,*a,**k):raise AssertionError('read path attempted write')
    def bind_profiles(self,*a,**k):raise AssertionError('read path attempted bind')

class FakeRuntime:
    def __init__(self):
        self.lock=threading.RLock(); self.generation='1'*64
        self.saved={'extensions':{'records':{'global':{'1':{}},'dns':{'2':{}},'group':{}}}}
        enc=lambda x:base64.b64encode(('cursor'+x).encode()).decode().rstrip('=')
        self.source={'nodes':[{'link':'NEVER-DISCLOSE-THIS-SECRET'}], 'metadata':{
            'configs':[{'id':enc('1'),'name':'正式配置','selected':True}, {'id':enc('3'),'name':'新配置','selected':False}],
            'dnss':[{'id':enc('2'),'name':'默认DNS','selected':True}],
            'groups':[{'id':enc('4'),'name':'测试分组'}]}}
        self.effective={'records':{'global':{'1':{},'3':{}},'dns':{'2':{}},'group':{'4':{}}}}
        self.proof={'beforeSha256':'2'*64,'afterSha256':'2'*64}
        self.running={'activeBundle':'3'*64,'configSha256':'4'*64,'sourceFingerprint':'a'*64,'InvocationID':'i'*32,'identityVerified':True}
        self.second=None;self.count=0;self.store=FakeStore(self)
    def snapshot(self,token):return copy.deepcopy(self.source),copy.deepcopy(self.proof),copy.deepcopy(self.effective),self.generation
    def status(self):
        self.count+=1
        return copy.deepcopy(self.second if self.count>1 and self.second else self.running)

class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.runtime=FakeRuntime()
        rb=types.ModuleType('bridge_m4.runtime_bundle');rb.fingerprints=lambda s,e:{'sourceSha256':'a'*64}
        uc=types.ModuleType('bridge_m4.upstream_contracts');uc.DAED_VERSION='v2.1.1';uc.DAE_VERSION='v2.1.1';uc.extension_fields=lambda s:{'test_field':{'type':'bool','default':'false','unsafe':'not returned'}}
        self.patch=patch.dict(sys.modules,{'bridge_m4':types.ModuleType('bridge_m4'),'bridge_m4.runtime_bundle':rb,'bridge_m4.upstream_contracts':uc})
        self.patch.start()
        spec=importlib.util.spec_from_file_location('bridge_m4.ui_metadata',ROOT/'bridge_m4/ui_metadata.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
    def tearDown(self):self.patch.stop()
    def run_projection(self):return self.module.metadata(self.runtime,'LOCAL_SESSION_ONLY',now=1234)
    def test_ids_decode(self):self.assertEqual(self.run_projection()['profiles']['group'][0]['id'],'4')
    def test_names_preserved(self):self.assertEqual(self.run_projection()['profiles']['global'][0]['name'],'正式配置')
    def test_selection_is_explicit(self):
        r=self.run_projection();self.assertTrue(r['profiles']['global'][0]['selected']);self.assertFalse(r['profiles']['group'][0]['selected'])
    def test_new_id_not_bound_from_memory(self):
        r=self.run_projection();self.assertTrue(r['profiles']['global'][0]['bound']);self.assertFalse(r['profiles']['global'][1]['bound'])
    def test_no_secret_in_projection(self):self.assertNotIn('NEVER-DISCLOSE',json.dumps(self.run_projection()))
    def test_only_type_exposed(self):self.assertEqual(self.run_projection()['specs']['dns'],{'test_field':{'type':'bool'}})
    def test_unchanged_verified(self):self.assertIs(self.run_projection()['modified'],False)
    def test_changed_source(self):
        self.runtime.running['sourceFingerprint']='b'*64;self.assertIs(self.run_projection()['modified'],True)
    def test_bad_runtime_identity_unknown(self):
        self.runtime.running['identityVerified']=False;self.assertIsNone(self.run_projection()['modified'])
    def test_runtime_changed_during_collection_unknown(self):
        self.runtime.second={**self.runtime.running,'activeBundle':'f'*64};self.assertIsNone(self.run_projection()['modified'])
    def test_source_proof_mismatch_unknown(self):
        self.runtime.proof['afterSha256']='f'*64;self.assertIsNone(self.run_projection()['modified'])
    def test_missing_proof_unknown(self):
        self.runtime.proof={};self.assertIsNone(self.run_projection()['modified'])
    def test_non_string_name_rejected(self):
        self.runtime.source['metadata']['configs'][0]['name']={};
        with self.assertRaises(ValueError):self.run_projection()
    def test_non_cursor_id_rejected(self):
        self.runtime.source['metadata']['configs'][0]['id']=base64.b64encode(b'other123').decode()
        with self.assertRaises(ValueError):self.run_projection()
    def test_invalid_base64_rejected(self):
        self.runtime.source['metadata']['configs'][0]['id']='!!!'
        with self.assertRaises(ValueError):self.run_projection()
    def test_overlong_id_rejected(self):
        self.runtime.source['metadata']['configs'][0]['id']='a'*300
        with self.assertRaises(ValueError):self.run_projection()
    def test_generation_race_rejected(self):
        old=self.runtime.snapshot
        def snap(t):
            r=old(t);self.runtime.generation='9'*64;return r
        self.runtime.snapshot=snap
        with self.assertRaises(ValueError):self.run_projection()
    def test_projection_does_not_mutate_inputs(self):
        before=json.dumps([self.runtime.source,self.runtime.effective,self.runtime.saved],sort_keys=True)
        self.run_projection();self.assertEqual(before,json.dumps([self.runtime.source,self.runtime.effective,self.runtime.saved],sort_keys=True))
    def test_counts(self):
        r=self.run_projection();self.assertEqual((r['nodeCount'],r['groupCount']),(1,1))
    def test_timestamp_and_version_scope(self):
        r=self.run_projection();self.assertEqual(r['observedAt'],1234);self.assertEqual(r['versions']['scope'],'installed-contract')
    def test_runtime_read_error_propagates(self):
        self.runtime.status=lambda:(_ for _ in ()).throw(RuntimeError('failed'))
        with self.assertRaises(RuntimeError):self.run_projection()
    def test_empty_collections(self):
        self.runtime.source={'nodes':[],'metadata':{'configs':[],'dnss':[],'groups':[]}}
        self.assertEqual(self.run_projection()['profiles'],{'global':[],'dns':[],'group':[]})
    def test_malicious_name_is_only_text(self):
        name='<img src=x onerror=alert(1)>'
        self.runtime.source['metadata']['configs'][0]['name']=name
        self.assertEqual(self.run_projection()['profiles']['global'][0]['name'],name)
    def test_no_default_guess(self):self.assertNotIn('default',json.dumps(self.run_projection()['specs']))

if __name__=='__main__':unittest.main(verbosity=2)
