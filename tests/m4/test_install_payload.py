import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import m4_install
from tests.m4.test_assets import fixture

class PayloadTests(unittest.TestCase):
    def test_bytecode_never_enters_immutable_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for d in ('out/m4-vendor/pkg/__pycache__','out/m2-official','official'): (root/d).mkdir(parents=True)
            (root/'out/m4-vendor/pkg/module.py').write_text('value=1\n')
            (root/'out/m4-vendor/pkg/__pycache__/module.cpython-313.pyc').write_bytes(b'old cache')
            (root/'out/m4-vendor/pkg/legacy.pyo').write_bytes(b'old cache')
            raw,lock=fixture({'geoip.dat':b'ip','geosite.dat':b'site','dae-linux-x86_64':b'dae'})
            (root/'official/dae.zip').write_bytes(raw)
            (root/'out/m2-official/dae').write_bytes(b'dae');(root/'out/m2-official/daed').write_bytes(b'daed')
            (root/'upstream.lock.json').write_text(json.dumps({'components':{'dae':lock,'daed':{'archive_members':[{'path':'daed-linux-x86_64','sha256':m4_install.digest(b'daed')}]}}}))
            with patch.object(m4_install,'ROOT',root),patch.object(m4_install,'UNITS',()),patch.object(m4_install,'PACKAGE_DIRS',()):
                first=m4_install.payload()
                (root/'out/m4-vendor/pkg/__pycache__/module.cpython-313.pyc').write_bytes(b'regenerated cache')
                self.assertEqual(first,m4_install.payload())
            self.assertFalse(any('__pycache__' in p or p.endswith(('.pyc','.pyo')) for p in first))
            self.assertIn(b'sys.dont_write_bytecode=True',first['/usr/local/bin/bridge-runner'][0])
            self.assertEqual(first['/opt/bridge-official/assets/geoip.dat'],(b'ip',0o444))

class InstalledIdentityTests(unittest.TestCase):
    def test_installed_authority_is_checked_before_replacement(self):
        from types import SimpleNamespace
        import stat
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'official';path.write_bytes(b'official')
            record={'files':{str(path):{'sha256':m4_install.digest(b'official'),'mode':0o555}}}
            good=dict(st_mode=stat.S_IFREG|0o555,st_nlink=1,st_uid=0,st_gid=0)
            with patch.object(Path,'lstat',return_value=SimpleNamespace(**good)):m4_install.verify_installed(record)
            for key,value in [('st_mode',stat.S_IFLNK|0o555),('st_mode',stat.S_IFREG|0o755),('st_nlink',2),('st_uid',1000),('st_gid',1000)]:
                with self.subTest(field=key,value=value),patch.object(Path,'lstat',return_value=SimpleNamespace(**dict(good,**{key:value}))):
                    with self.assertRaisesRegex(RuntimeError,'INSTALLED_FILE_AUTHORITY'):m4_install.verify_installed(record)
            path.write_bytes(b'changed')
            with patch.object(Path,'lstat',return_value=SimpleNamespace(**good)):
                with self.assertRaisesRegex(RuntimeError,'INSTALLED_FILE_CHANGED'):m4_install.verify_installed(record)
