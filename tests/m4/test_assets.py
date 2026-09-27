import hashlib
import io
import unittest
import zipfile
from scripts.m4_assets import official_assets


def fixture(files=None):
    files=files or {'geoip.dat':b'synthetic-ip','geosite.dat':b'synthetic-site'}
    target=io.BytesIO()
    with zipfile.ZipFile(target,'w') as z:
        for name,body in files.items():z.writestr(name,body)
    raw=target.getvalue()
    return raw,{'sha256':hashlib.sha256(raw).hexdigest(),'archive_members':[{'path':n,'size':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in files.items()]}

class AssetsTests(unittest.TestCase):
    def test_verified_bytes(self):
        raw,lock=fixture();self.assertEqual(official_assets(raw,lock)['geoip.dat'],b'synthetic-ip')
    def test_archive_corruption(self):
        raw,lock=fixture()
        with self.assertRaisesRegex(ValueError,'ARCHIVE_HASH'):official_assets(raw+b'changed',lock)
    def test_member_corruption(self):
        raw,lock=fixture();lock['archive_members'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'MEMBER_HASH'):official_assets(raw,lock)
    def test_missing_member(self):
        raw,lock=fixture({'geoip.dat':b'synthetic-ip'})
        with self.assertRaisesRegex(ValueError,'ASSETS_MISSING'):official_assets(raw,lock)
    def test_member_set(self):
        raw,lock=fixture();lock['archive_members'].pop()
        with self.assertRaisesRegex(ValueError,'MEMBER_SET'):official_assets(raw,lock)
