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

    def test_runtime_manifest_accepts_frontend_and_checks_hash(self):
        # Execute the actual manifest function against an in-memory filesystem;
        # unrelated controller/schema dependencies are unnecessary for this check.
        import ast
        from unittest.mock import Mock
        source=(Path(__file__).resolve().parents[2]/'bridge_m4/authority.py').read_text()
        function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='manifest')
        def check(ok,code):
            if not ok:raise RuntimeError(code)
        for name in ('/opt/bridge-daed-web/index.html','/opt/bridge-daed-web-entry/connect.js'):
            body=b'official fixture'
            record={'schemaVersion':1,'files':{name:{'sha256':hashlib.sha256(body).hexdigest(),'mode':0o444}}}
            for actual,expected in ((body,True),(b'changed',False)):
                scope={'Path':Path,'MANIFEST':Path('/etc/daed-independent-bridge/install.json'),
                       'directory':Mock(return_value=123),'os':Mock(),'check':check,
                       'load_json':json.loads,'digest':lambda b:hashlib.sha256(b).hexdigest(),
                       'read_at':Mock(side_effect=[json.dumps(record).encode(),actual])}
                exec(compile(ast.Module(body=[function],type_ignores=[]),'authority.py','exec'),scope)
                if expected:self.assertEqual(scope['manifest'](),record)
                else:
                    with self.assertRaisesRegex(RuntimeError,'INSTALL_FILE_IDENTITY'):scope['manifest']()

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
        self.assertIn('listen 192.0.2.1:2023;',config)
        self.assertIn('index index.html;',config)
        self.assertIn('location = / { try_files /index.html =404; }',config)
        self.assertIn('proxy_pass http://127.0.0.1:2025/graphql;',config)
        self.assertIn('proxy_read_timeout 180s;',config)
        self.assertNotIn('listen 192.0.2.1:2024',config)
        self.assertNotIn('8444',config)
        for address in ('0; shutdown','example.invalid','192.0.2.1\nroot /;'):
            with self.assertRaises(ValueError):configuration(address)
    def test_official_default_endpoint_without_launcher(self):
        root=Path(__file__).resolve().parents[2]
        self.assertFalse((root/'deployment/release/daed-web/connect.js').exists())
        unit=(root/'deployment/m4/units/daed-api.service').read_text()
        self.assertIn('--api-only',unit);self.assertIn('--listen 127.0.0.1:2024',unit)
    def test_existing_version_stop_skips_missing_web_only(self):
        from scripts import release_lifecycle as lifecycle
        from unittest.mock import patch
        from types import SimpleNamespace
        with patch.object(Path,'exists',return_value=False),patch.object(lifecycle,'ctl',return_value=SimpleNamespace(stdout=b'ActiveState=inactive\nMainPID=0\n')) as calls:
            lifecycle.stop()
        self.assertFalse(any('daed-web.service' in c.args for c in calls.call_args_list))
        self.assertTrue(any('dae.service' in c.args for c in calls.call_args_list))
