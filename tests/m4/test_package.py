import hashlib,json,os
from pathlib import Path
import tempfile
import unittest
from scripts.m4_package import verify,wheels_payload

class PackageTests(unittest.TestCase):
    def fixture(self,root):
        body=b'synthetic code';(root/'app.py').write_bytes(body);(root/'app.py').chmod(0o444)
        raw=json.dumps({'schemaVersion':1,'checkoutSha':'a'*40,'files':{'app.py':hashlib.sha256(body).hexdigest()}}).encode()
        (root/'deployment-manifest.json').write_bytes(raw);return hashlib.sha256(raw).hexdigest()
    def test_exact_readonly_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);pin=self.fixture(p);self.assertEqual(verify(p,pin)['checkoutSha'],'a'*40)
    def test_tampered_missing_extra_writable_and_links(self):
        for fault in ('tamper','missing','extra','writable','symlink','hardlink'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temp:
                p=Path(temp);pin=self.fixture(p);f=p/'app.py'
                if fault=='tamper':f.chmod(0o644);f.write_bytes(b'changed');f.chmod(0o444)
                elif fault=='missing':f.unlink()
                elif fault=='extra':(p/'unexpected').write_text('extra')
                elif fault=='writable':f.chmod(0o644)
                elif fault=='symlink':f.unlink();f.symlink_to('deployment-manifest.json')
                elif fault=='hardlink':os.link(f,p/'alias')
                with self.assertRaises(RuntimeError):verify(p,pin)
    def test_manifest_pin_required(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);self.fixture(p)
            for pin in ('', 'f'*64):
                with self.assertRaises(RuntimeError):verify(p,pin)
    def test_dependency_hash_set_and_collision(self):
        import io,zipfile
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('synthetic/__init__.py',b'value=1')
        raw=b.getvalue();lock='synthetic==1.0 --hash=sha256:'+hashlib.sha256(raw).hexdigest()
        self.assertEqual(wheels_payload(lock,{'synthetic-1.0-py3-none-any.whl':raw}),{'synthetic/__init__.py':b'value=1'})
        for wheels in ({},{'synthetic-1.0-py3-none-any.whl':raw+b'x'},{'other-1.0-py3-none-any.whl':raw}):
            with self.assertRaises(RuntimeError):wheels_payload(lock,wheels)
