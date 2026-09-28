import copy
import unittest
from bridge_m1.common import canonical,digest,load_json
from bridge_m2.bundle import FILES
from bridge_m2.security import Denied
from bridge_m4.extensions import split
from bridge_m4.runtime_bundle import artifacts,fingerprints,receipt,make,verify_bundle
from tests.m4.test_convert import example


def fixture():
    source,ext=example()
    from bridge_m4.convert import cursor
    for index,group in enumerate(source["metadata"]["groups"],1):group["id"]=cursor(str(index))
    ext.update(schemaVersion=1,classification='REGENERATED_INDEPENDENT_BRIDGE_INPUT',sourceSha256='1'*64,databaseSha256='2'*64)
    sha=digest(canonical(source))
    proof={'method':'two-complete-normalized-fingerprints','beforeSha256':sha,'afterSha256':sha,'attempts':1,'pages':[2,2],'transactional':False}
    return source,ext,proof

class RuntimeBundleTests(unittest.TestCase):
    def setUp(self):self.source,self.ext,self.proof=fixture()
    def payload(self):return {n:b for n,b in artifacts(self.source,self.proof,self.ext).items() if n in FILES}
    def test_receipt_bundle_and_ir_bind_extensions(self):
        r=receipt(self.source,self.ext,100);payload=self.payload();ident,bundle=make(payload,r,None,101)
        env=verify_bundle(bundle,ident,r,102)
        self.assertEqual(env['extensionsSha256'],r['extensionsSha256'])
        self.assertEqual(env['sourceSha256'],load_json(payload['normalized-ir.json'])['sourceFingerprint'])
        self.assertNotEqual(r['sourceSha256'],r['graphqlSha256'])
    def test_extension_change_invalidates_receipt(self):
        r=receipt(self.source,self.ext,100)
        record=self.ext['records']['global']['1']
        _,self.ext['records']['global']['1']=split(record['sourceText'].replace('disable_thp: false','disable_thp: true'),'global')
        with self.assertRaisesRegex(Denied,'OLD_SOURCE'):make(self.payload(),r,None,101)
    def test_missing_extension(self):
        del self.ext['records']['global']
        with self.assertRaisesRegex(Denied,'EXTENSION_SCHEMA'):self.payload()
    def test_wrong_extension_version(self):
        self.ext['daedVersion']='v0'
        with self.assertRaisesRegex(Denied,'EXTENSION_VERSION'):self.payload()
    def test_tamper_every_candidate_file(self):
        p=self.payload();r=receipt(self.source,self.ext,100);ident,b=make(p,r,None,101)
        for name in b:
            with self.subTest(file=name):
                modified=dict(b);modified[name]+=b' '
                with self.assertRaises(Exception):verify_bundle(modified,ident,r,102)
    def test_expired_receipt_and_bundle(self):
        r=receipt(self.source,self.ext,100,10);p=self.payload()
        with self.assertRaisesRegex(Denied,'SOURCE_EXPIRED'):make(p,r,None,110)
        ident,b=make(p,r,None,101)
        with self.assertRaisesRegex(Denied,'BUNDLE_EXPIRED'):verify_bundle(b,ident,r,110)
    def test_receipt_missing_extension_hash(self):
        r=receipt(self.source,self.ext,100);del r['extensionsSha256']
        with self.assertRaisesRegex(Denied,'RECEIPT_SHAPE'):make(self.payload(),r,None,101)
    def test_recomputed_manifest_cannot_authorize_modified_config(self):
        r=receipt(self.source,self.ext,100);p=self.payload();p['candidate.dae']+=b'\n'
        m=load_json(p['manifest.json']);m['files']['candidate.dae']={'sha256':digest(p['candidate.dae']),'size':len(p['candidate.dae'])};p['manifest.json']=canonical(m)
        with self.assertRaisesRegex(Denied,'RENDER_MISMATCH'):make(p,r,None,101)
    def test_alternating_edits_preserve_ownership(self):
        previous=copy.deepcopy(self.source)
        self.source['metadata']['configs'][0]['global']['logLevel']='debug'
        record=self.ext['records']['global']['1'];_,self.ext['records']['global']['1']=split(record['sourceText'].replace('disable_thp: false','disable_thp: true'),'global')
        self.source['metadata']['configs'][0]['global']['logLevel']='info'
        sha=digest(canonical(self.source));self.proof.update(beforeSha256=sha,afterSha256=sha)
        payload=self.payload()
        self.assertIn(b'disable_thp: true',payload['candidate.dae'])
        self.assertEqual(previous['metadata']['groups'],self.source['metadata']['groups'])
        self.assertEqual(previous['nodes'],self.source['nodes'])
    def test_joint_fingerprint_is_deterministic(self):
        self.assertEqual(fingerprints(self.source,self.ext),fingerprints(copy.deepcopy(self.source),copy.deepcopy(self.ext)))
