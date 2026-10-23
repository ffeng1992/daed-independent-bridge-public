"""Automatic final-payload planning; no production filesystem writes."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from scripts import management_payload as payload
from scripts import release_management_plan as planner


class PayloadUpgradeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for p in payload.PACKAGES:(self.root/p).mkdir()
        (self.root/'scripts').mkdir()
        for n in (*payload.SCRIPTS,'bridge_m2/control.py','bridge_m4/authority.py','bridge_m4/web.py'):
            (self.root/n).write_text('candidate\n')
        (self.root/'upstream.lock.json').write_text('{}')
        self.package=payload.generate(self.root)
        self.old={'schemaVersion':1,'files':{
            '/opt/bridge/'+n:{'sha256':pin['sha256'],'mode':pin['mode']}
            for n,pin in self.package['files'].items()}}
        self.old['files']['/opt/bridge/upstream.lock.json']={'sha256':payload.sha(b'{}'),'mode':0o644}
    def plan(self):return planner.build_plan(self.old,self.root)
    def test_deterministic_final_bytes(self):
        self.assertEqual(self.package,payload.generate(self.root))
        self.assertEqual(self.plan()['changes'],[])
    def test_add_modify_delete_automatic(self):
        (self.root/'bridge_m4/new.py').write_text('new')
        self.old['files']['/opt/bridge/bridge_m4/web.py']['sha256']='b'*64
        self.old['files']['/opt/bridge/bridge_m4/retired.py']={'sha256':'c'*64,'mode':0o644}
        ops={r['source']:r['operation'] for r in self.plan()['changes']}
        self.assertEqual(ops,{'bridge_m4/new.py':'add','bridge_m4/web.py':'modify','bridge_m4/retired.py':'delete'})
    def test_old_release_hash_not_a_version_whitelist(self):
        self.old['files']['/opt/bridge/bridge_m4/web.py']['sha256']='c'*64
        self.assertEqual(len(self.plan()['changes']),1)
    def test_frozen_package_detects_tampering(self):
        (self.root/'bridge_m4/web.py').write_text('tampered')
        with self.assertRaisesRegex(RuntimeError,'PACKAGE_INTEGRITY'):
            planner.build_plan(self.old,self.root,self.package)
    def test_official_lock_refused(self):
        (self.root/'upstream.lock.json').write_text('{"changed":1}')
        with self.assertRaisesRegex(RuntimeError,'UPSTREAM_CHANGE'):self.plan()
    def test_foreign_install_refused(self):
        del self.old['files']['/opt/bridge/bridge_m2/control.py']
        with self.assertRaisesRegex(RuntimeError,'UNSUPPORTED_INSTALLATION'):self.plan()
    def test_unknown_manifest_format_refused(self):
        self.old['schemaVersion']=2
        with self.assertRaisesRegex(RuntimeError,'INSTALL_MANIFEST'):self.plan()
    def test_dns_and_official_files_preserved(self):
        for n in ('/etc/systemd/system/dae.service','/opt/bridge-official/dae','/etc/systemd/system/bridge-lan-dns.service'):
            self.old['files'][n]={'sha256':'a'*64,'mode':0o644}
        self.assertEqual(self.plan()['changes'],[])
    def test_package_permissions_dependencies(self):
        self.assertEqual(self.package['dependencies']['modules'],['graphql','jsonschema'])
        self.assertTrue(all(x['mode']==0o644 and x['owner']==x['group']=='root' for x in self.package['files'].values()))
    def test_symlink_refused(self):
        (self.root/'bridge_m4/alias.py').symlink_to('web.py')
        with self.assertRaisesRegex(RuntimeError,'SOURCE_LINK'):self.plan()

if __name__=='__main__':unittest.main()
