import copy,json,unittest,re
from pathlib import Path
from bridge_m1.common import ROOT,Rejected
from bridge_m1.emit import scalar
from bridge_m4.collect import collect
from bridge_m4.convert import normalize,emit,cursor,FIELDS
from bridge_m4.extensions import split,CompatibilityError
from bridge_m4.document import parse
from bridge_m1.collect import EXPECTED_GLOBAL

class Reader:
    def __init__(self):
        self.s=json.loads((ROOT/'fixtures/m1/success/routed.json').read_text());self.calls=0;self.changing=False
    def __call__(self,op,v):
        if op=='GlobalCapabilities':
            self.calls+=1;return {'data':{'__type':{'fields':[{'name':x} for x in sorted(EXPECTED_GLOBAL)]}}}
        if op=='SnapshotMetadata':
            d=copy.deepcopy(self.s['metadata']['data'])
            if self.changing:d['configs'][0]['name']=str(self.calls)
            return {'data':d}
        nodes=[n for p in self.s['nodePages'] if p['subscriptionId']==v['subscriptionId'] for n in p['response']['data']['nodes']['edges']]
        start=next(i+1 for i,n in enumerate(nodes) if n['id']==v['after']) if v['after'] else 0
        edges=nodes[start:start+v['first']]
        return {'data':{'nodes':{'totalCount':len(nodes),'edges':copy.deepcopy(edges),'pageInfo':{'startCursor':edges[0]['id'] if edges else None,'endCursor':edges[-1]['id'] if edges else None,'hasNextPage':start+len(edges)<len(nodes)}}}}

def example():
    source,proof=collect(Reader(),page_size=1)
    source['metadata']['configs'][0]['id']=cursor('1');source['metadata']['dnss'][0]['id']=cursor('1')
    glob=source['metadata']['configs'][0]['global']
    text='global {\n'+''.join(' '+f['dae']+': '+scalar(glob[f['graphql']])+'\n' for f in FIELDS if f['dae']!='so_mark_from_dae_set' and (f['dae']!='so_mark_from_dae' or glob['soMarkFromDaeSet']))+' disable_thp: false\n}\n'
    _,g=split(text,'global');_,d=split('dns {\n'+source['metadata']['dnss'][0]['dns']['string']+'\n}\n','dns')
    return source,{'daedVersion':'v2.1.1','records':{'global':{'1':g},'dns':{'1':d}}}

class CompatibilityConversionTests(unittest.TestCase):
    def test_collection_double_snapshot(self):
        source,p=collect(Reader(),page_size=1)
        self.assertFalse(source['synthetic']);self.assertEqual(p['beforeSha256'],p['afterSha256']);self.assertEqual(p['pages'],[2,2])
    def test_source_changed(self):
        r=Reader();r.changing=True
        with self.assertRaisesRegex(Rejected,'SOURCE_CHANGED'):collect(r)
    def test_membership_order_preserved(self):
        r=Reader();r.s['metadata']['data']['groups'][0]['nodes']=[{'id':'bm9kZS0y'},{'id':'bm9kZS0x'}]
        source,_=collect(r);self.assertEqual(source['metadata']['groups'][0]['nodes'],r.s['metadata']['data']['groups'][0]['nodes'])
    def test_determinism_and_extension(self):
        s,e=example();ir=normalize(s,e);out=emit(ir)
        self.assertEqual(out,emit(normalize(copy.deepcopy(s),copy.deepcopy(e))))
        self.assertIn(b'disable_thp: false',out);self.assertIn(b'max_cache_size: 0',out)
        self.assertEqual(len(ir.compatibility_defaults),3)
    def test_daed_managed_update_preserves_extension(self):
        s,e=example();s['metadata']['configs'][0]['global']['logLevel']='debug'
        out=emit(normalize(s,e));self.assertIn(b'log_level: \"debug\"',out);self.assertIn(b'disable_thp: false',out)
    def test_missing_node(self):
        s,e=example();s['metadata']['groups'][0]['nodes']=[{'id':'absent'}]
        with self.assertRaisesRegex(CompatibilityError,'MISSING_NODE'):normalize(s,e)
    def test_unknown_protocol(self):
        s,e=example();s['nodes'][0]['protocol']='unknown'
        with self.assertRaisesRegex(CompatibilityError,'UNSUPPORTED_TARGET_NODE_PROTOCOL'):normalize(s,e)
    def test_lossless_document(self):
        text='routing {\n # synthetic\n domain(suffix: "例子.invalid") -> direct\n fallback: block\n}\n'
        self.assertEqual(parse(text,'routing').render(),text)
    def test_reject_appended_section(self):
        with self.assertRaisesRegex(CompatibilityError,'EXTRA_DOCUMENT_SECTION'):
            parse('routing {} include {"/etc/private"}','routing')
    def test_route_order(self):
        a='routing {\n domain("x.invalid") -> block\n domain("x.invalid") -> direct\n fallback: direct\n}'
        b=a.replace('-> block','-> TEMP').replace('-> direct','-> block',1).replace('-> TEMP','-> direct')
        self.assertNotEqual(parse(a,'routing'),parse(b,'routing'))

class ArtifactTests(unittest.TestCase):
    def test_five_outputs_and_hashes(self):
        from bridge_m4.artifacts import artifacts
        from bridge_m1.common import canonical,digest
        s,e=example();fingerprint=digest(canonical(s));p={'beforeSha256':fingerprint,'afterSha256':fingerprint}
        files=artifacts(s,p,e)
        self.assertEqual(set(files),{'candidate.dae','source-snapshot.json','normalized-ir.json','conversion-report.json','manifest.json','SHA256SUMS'})
        for name,h in json.loads(files['manifest.json'])['files'].items():self.assertEqual(h,digest(files[name]))
        self.assertEqual(files,artifacts(s,p,e))
    def test_bad_snapshot_binding(self):
        from bridge_m4.artifacts import artifacts
        s,e=example()
        with self.assertRaisesRegex(CompatibilityError,'SOURCE_FINGERPRINT_MISMATCH'):
            artifacts(s,{'beforeSha256':'bad','afterSha256':'bad'},e)
    def test_group_check_override(self):
        s,e=example();g=s['metadata']['groups'][0];g['id']=cursor('1')
        _,r=split('group {\n check_interval: "45s"\n tcp_check_http_method: "GET"\n}\n','group')
        e['records']['group']={'1':r}
        out=emit(normalize(s,e));self.assertIn(b'check_interval: "45s"',out);self.assertIn(b'tcp_check_http_method: "GET"',out)

class PresenceMetadataTests(unittest.TestCase):
    def test_explicit_zero_mark_vs_absent(self):
        s,e=example();s['metadata']['configs'][0]['global']['soMarkFromDae']=0
        s['metadata']['configs'][0]['global']['soMarkFromDaeSet']=False
        self.assertFalse(bool(re.search(rb'\n\s+so_mark_from_dae:',emit(normalize(s,e)))))
        s['metadata']['configs'][0]['global']['soMarkFromDaeSet']=True
        out=emit(normalize(s,e));self.assertTrue(bool(re.search(rb'\n\s+so_mark_from_dae: 0\n',out)));self.assertFalse(b'so_mark_from_dae_set:' in out)
    def test_metadata_rejected_in_text(self):
        with self.assertRaisesRegex(CompatibilityError,'INTERNAL_METADATA_NOT_CONFIG_FIELD'):
            split('global {\n so_mark_from_dae_set: true\n}','global')
    def test_fixture_file_permissions(self):
        import contextlib,io,tempfile
        from unittest.mock import patch
        from scripts import m4_prepare
        with tempfile.TemporaryDirectory() as directory:
            fake=Path(directory)/'scripts/m4_prepare.py'
            with patch.object(m4_prepare,'__file__',str(fake)),contextlib.redirect_stdout(io.StringIO()):m4_prepare.main()
            root=Path(directory)/'out/m4-candidates'
            self.assertEqual(root.stat().st_mode&0o777,0o700)
            for path in root.iterdir():self.assertEqual(path.stat().st_mode&0o777,0o600)
