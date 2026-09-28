import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bridge_m4.runtime import Runtime
from bridge_m4.store import ExtensionStore
from bridge_m2.security import Denied
from tests.m4.test_runtime_bundle import fixture

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.root.chmod(0o700);(self.root/'extensions').mkdir(mode=0o700)
        self.source,self.ext,self.proof=fixture();ExtensionStore(self.root/'extensions').commit(self.ext)
        self.calls=[]
        self.uid_patch=patch('bridge_m4.runtime.os.geteuid',return_value=os.getuid() or 1000)
        if os.getuid()==0:self.skipTest('nonprivileged runtime test requires user context')
        self.runtime=Runtime(self.root,submitter=self.submit,collector=lambda t:(self.source,self.proof))
    def submit(self,action,bundle=None):self.calls.append((action,bundle));return {'state':'stopped','activeBundle':None}
    def test_preview_does_not_apply_or_control_service(self):
        p=self.runtime.preview('synthetic');self.assertEqual(self.calls,[]);self.assertIn('extensionsSha256',p)
    def test_preview_determinism(self):
        a=self.runtime.preview('synthetic');b=self.runtime.preview('synthetic');self.assertEqual(a['previewId'],b['previewId']);self.assertFalse(b['changedSincePreview'])
    def test_extensions_have_no_raw_credentials(self):
        value=self.runtime.extensions();self.assertNotIn('sourceText',json.dumps(value));self.assertNotIn('sourceSha256',json.dumps(value))
    def test_edit_invalidates_preview(self):
        p=self.runtime.preview('synthetic');generation=self.runtime.extensions()['generation']
        self.runtime.edit({'expected':generation,'section':'global','profile':'1','field':'disable_thp','state':{'present':True,'value':True}})
        with self.assertRaisesRegex(Denied,'PREVIEW_CONFLICT'):self.runtime.require_preview(p['previewId'])
        self.assertEqual(self.calls,[])
    def test_daed_change_preserves_extension_generation(self):
        p=self.runtime.preview('synthetic');self.source['metadata']['configs'][0]['global']['logLevel']='debug'
        from bridge_m1.common import canonical,digest
        sha=digest(canonical(self.source));self.proof.update(beforeSha256=sha,afterSha256=sha)
        second=self.runtime.preview('synthetic');self.assertEqual(p['extensionGeneration'],second['extensionGeneration']);self.assertNotEqual(p['previewId'],second['previewId'])
    def test_new_official_profiles_bind_without_losing_existing_extensions(self):
        import copy,base64
        from bridge_m1.common import canonical,digest,load_json
        from bridge_m4.convert import bind_new_profiles
        from bridge_m4.runtime_bundle import fingerprints
        original=copy.deepcopy(self.ext)
        for kind in ('configs','dnss'):
            item=copy.deepcopy(self.source['metadata'][kind][0])
            self.source['metadata'][kind][0]['selected']=False
            item.update(id=base64.b64encode(b'cursor99').decode().rstrip('='),selected=True)
            self.source['metadata'][kind].append(item)
        sha=digest(canonical(self.source));self.proof.update(beforeSha256=sha,afterSha256=sha)
        preview=self.runtime.preview('synthetic')
        effective=bind_new_profiles(self.source,original)
        self.assertEqual(preview['sourceFingerprint'],fingerprints(self.source,effective)['sourceSha256'])
        ir=load_json((self.root/'previews'/preview['previewId']/'normalized-ir.json').read_bytes())
        self.assertEqual(ir['extensions'],effective)
        self.assertEqual(ExtensionStore(self.root/'extensions').load()[1]['extensions'],original)
        self.assertEqual(effective['records']['global']['1'],original['records']['global']['1'])
        self.assertEqual(self.calls,[])

    def test_no_apply_before_validate(self):
        p=self.runtime.preview('synthetic')
        with self.assertRaisesRegex(Denied,'VALIDATION_REQUIRED'):self.runtime.apply('synthetic',p['previewId'])
        self.assertEqual(self.calls,[])
    def test_fixed_action_allowlist(self):
        with self.assertRaisesRegex(Denied,'ACTION_REJECTED'):self.runtime.action('arbitrary')
        self.assertEqual(self.calls,[])

    @patch('bridge_m4.runtime.time.sleep')
    def test_status_retries_only_busy(self,sleep):
        with patch.object(self.runtime,'submit',side_effect=[{'error':'BUSY'},{'state':'stopped'}]) as submit:
            self.assertEqual(self.runtime.action('status'),{'state':'stopped'})
            self.assertEqual(submit.call_count,2)
        with patch.object(self.runtime,'submit',return_value={'error':'IDENTITY'}) as submit:
            self.assertEqual(self.runtime.status(),{'error':'IDENTITY'})
            self.assertEqual(submit.call_count,1)
    @patch('bridge_m4.runtime.time.sleep')
    def test_status_busy_exhaustion_fails_closed(self,sleep):
        with patch.object(self.runtime,'submit',return_value={'error':'BUSY'}) as submit:
            self.assertEqual(self.runtime.status(),{'error':'BUSY'})
            self.assertEqual(submit.call_count,6)
    def test_mutation_busy_is_never_retried(self):
        for action in ('start','stop','reload','recover'):
            with patch.object(self.runtime,'submit',return_value={'error':'BUSY'}) as submit:
                self.assertEqual(self.runtime.action(action),{'error':'BUSY'})
                self.assertEqual(submit.call_count,1)
