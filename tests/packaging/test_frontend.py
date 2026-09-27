import hashlib
import io
import json
from pathlib import Path
import tarfile
import unittest
from bridge_m4.official_web import configuration
from scripts.release_frontend import unpack

class FrontendTests(unittest.TestCase):
    def test_fixed_frontend_install_paths(self):
        from scripts.m4_install_transaction import allowed
        self.assertTrue(allowed('/opt/bridge-daed-web/index.html'))
        self.assertTrue(allowed('/opt/bridge-daed-web-entry/connect.js'))
        self.assertFalse(allowed('/opt/bridge-daed-web-other/index.html'))

    def fixture(self,changes=None):
        files={'index.html':b'<html>official synthetic</html>','assets/app.js':b'official synthetic'}
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w:gz') as archive:
            for n,b in (changes or files).items():
                m=tarfile.TarInfo('web/'+n);m.size=len(b);archive.addfile(m,io.BytesIO(b))
        raw=buf.getvalue()
        pin={'sha256':hashlib.sha256(raw).hexdigest(),'archivePrefix':'web/',
             'files':[{'path':n,'size':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in files.items()]}
        return raw,pin,files
    def test_exact_unmodified_assets(self):
        raw,pin,files=self.fixture();self.assertEqual(unpack(raw,pin),files)
    def test_archive_member_and_path_failure(self):
        raw,pin,_=self.fixture()
        with self.assertRaisesRegex(RuntimeError,'ARCHIVE_HASH'):unpack(raw+b'x',pin)
        for changes in ({'index.html':b'changed'}, {'../escape':b'x'}):
            raw,_,_=self.fixture(changes);pin['sha256']=hashlib.sha256(raw).hexdigest()
            with self.assertRaises(RuntimeError):unpack(raw,pin)
    def test_proxy_is_fixed_loopback_and_frontend_tls(self):
        config=configuration('192.0.2.1')
        self.assertIn('listen 192.0.2.1:8444 ssl;',config)
        self.assertIn('proxy_pass http://127.0.0.1:2023/graphql;',config)
        self.assertNotIn('listen 192.0.2.1:2023',config)
        for address in ('0; shutdown','example.invalid','192.0.2.1\nroot /;'):
            with self.assertRaises(ValueError):configuration(address)
    def test_launcher_uses_real_official_key_not_credentials(self):
        root=Path(__file__).resolve().parents[2]
        js=(root/'deployment/release/daed-web/connect.js').read_text()
        self.assertIn("localStorage.setItem('endpointURL', location.origin + '/graphql')",js)
        self.assertIn("location.replace('/index.html' + location.hash)",js)
        self.assertNotIn("setItem('token'",js)
        unit=(root/'deployment/m4/units/daed-api.service').read_text()
        self.assertIn('--api-only',unit);self.assertIn('--listen 127.0.0.1:2023',unit)
    def test_existing_version_stop_skips_missing_web_only(self):
        from scripts import release_lifecycle as lifecycle
        from unittest.mock import patch
        from types import SimpleNamespace
        with patch.object(Path,'exists',return_value=False),patch.object(lifecycle,'ctl',return_value=SimpleNamespace(stdout=b'ActiveState=inactive\nMainPID=0\n')) as calls:
            lifecycle.stop()
        self.assertFalse(any('daed-web.service' in c.args for c in calls.call_args_list))
        self.assertTrue(any('dae.service' in c.args for c in calls.call_args_list))
