import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import bridge_m4
from bridge_m4 import asset_authority as authority, capability_contract as capability
from bridge_m1.common import Rejected
from bridge_m2.security import Denied


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.policy=Path(t.name)/'policy.json'
        self.write({})
    def write(self, fields):self.policy.write_text(json.dumps({'schemaVersion':1,'reviewedUnconsumed':fields}))
    def check(self,names):capability.verify([{'name':n} for n in names],{'required'},policy_path=self.policy)
    def test_exact_consumed_fields_pass(self):self.check(['required'])
    def test_missing_consumed_field_rejected(self):
        with self.assertRaises(Rejected):self.check([])
    def test_duplicate_field_rejected(self):
        with self.assertRaises(Rejected):self.check(['required','required'])
    def test_unknown_addition_rejected(self):
        with self.assertRaises(Rejected):self.check(['required','added'])
    def test_reviewed_unconsumed_addition_allowed(self):
        self.write({'added':'reviewed synthetic addition'});self.check(['required','added'])
    def test_consumed_field_cannot_be_declared_ignored(self):
        self.write({'required':'not allowed'})
        with self.assertRaises(Rejected):self.check(['required'])


class AssetTests(unittest.TestCase):
    @contextlib.contextmanager
    def geodata(self, generation, current):
        module=types.ModuleType('bridge_m4.geodata')
        module.generation=Mock(return_value=generation)
        module.current_id=Mock(return_value=current)
        module.selected_hashes_from_folder=Mock(return_value={'geoip.dat':'i','geosite.dat':'s'})
        with patch.dict(sys.modules,{'bridge_m4.geodata':module}),patch.object(bridge_m4,'geodata',module,create=True):
            yield module
    def test_dynamic_data_does_not_read_static_fallback(self):
        with self.geodata((Path('/versions')/('a'*64),{}),'a'*64),patch('bridge_m2.security.directory') as read:
            self.assertEqual(authority.verify_active_assets({'files':{}}),{'geoip.dat':'i','geosite.dat':'s'})
            read.assert_not_called()
    def test_bad_dynamic_data_never_falls_back(self):
        with self.geodata((None,None),None) as data,patch('bridge_m2.security.directory') as read:
            data.generation.side_effect=RuntimeError('GEODATA_FILE_HASH')
            with self.assertRaisesRegex(RuntimeError,'GEODATA_FILE_HASH'):authority.verify_active_assets({'files':{}})
            read.assert_not_called()
    def test_pointer_change_is_rejected(self):
        with self.geodata((Path('/versions')/('a'*64),{}),'a'*64) as data:
            data.current_id.side_effect=['a'*64,'b'*64]
            with self.assertRaisesRegex(Denied,'SELECTED_CHANGED'):authority.verify_active_assets({'files':{}})
    def test_current_static_assets_are_still_hash_verified(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'assets';folder.mkdir(mode=0o755)
            files={};names=set()
            for n in ('geoip.dat','geosite.dat'):
                p=folder/n;b=n.encode();p.write_bytes(b);p.chmod(0o444);names.add(str(p))
                files[str(p)]={'sha256':hashlib.sha256(b).hexdigest(),'mode':0o444}
            # Preserve real descriptor-relative read and permission checks,
            # injecting only fixture ownership when CI is non-root.
            from bridge_m2 import security
            origdir,origread=security.directory,security.read_at
            with self.geodata((None,None),None),patch.object(authority,'ASSET_FILES',names), \
                 patch.object(security,'directory',side_effect=lambda p,u,g,m:origdir(p,os.geteuid(),os.getegid(),m)), \
                 patch.object(security,'read_at',side_effect=lambda fd,n,u,g,m,**kw:origread(fd,n,os.geteuid(),os.getegid(),m,**kw)):
                self.assertEqual(set(authority.verify_active_assets({'files':files})),{'geoip.dat','geosite.dat'})
                p=folder/'geoip.dat';p.chmod(0o644);p.write_bytes(b'broken');p.chmod(0o444)
                with self.assertRaisesRegex(Denied,'ACTIVE_ASSET_IDENTITY'):authority.verify_active_assets({'files':files})
    def test_missing_static_pin_is_not_ignored(self):
        with self.geodata((None,None),None):
            with self.assertRaisesRegex(Denied,'ASSET_IDENTITY_MISSING'):authority.verify_active_assets({'files':{}})
