import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import export_public as export

class ExportTests(unittest.TestCase):
    def files(self):return {'VERSION':(0o644,b'1.0.0\n'),'install.sh':(0o755,b'#!/bin/sh\nexit 0\n')}
    def test_repeat_export_bytes_and_modes(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(export,'files_at',return_value=('a'*40,self.files())):
            first=Path(tmp)/'a';second=Path(tmp)/'b'
            self.assertEqual(export.export('main',first),export.export('main',second))
            self.assertEqual(export.verify(first),export.verify(second))
            self.assertEqual((first/'.public-source.json').read_bytes(),(second/'.public-source.json').read_bytes())
            for n in self.files():self.assertEqual((first/n).read_bytes(),(second/n).read_bytes())
    def test_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(export,'files_at',return_value=('a'*40,self.files())):
            with self.assertRaisesRegex(RuntimeError,'OUTPUT_MUST_NOT_EXIST'):export.export('main',Path(tmp))
    def test_site_paths_ips_keys_and_tokens_rejected(self):
        values=['/'+ 'Users'+'/synthetic/private', '.'.join(['10','20','30','40']),
                '-----BEGIN '+'OPENSSH PRIVATE KEY-----', 'gh'+'p_'+'x'*36,
                'dae'+'d-shanghai', '\u4e0a\u6d77']
        for text in values:
            with self.subTest(case=values.index(text)),self.assertRaises(RuntimeError):export.scan('file.txt',text.encode())
    def test_forbidden_files_rejected(self):
        for name in ('../escape','out/test.txt','secrets.db','credentials.key','primary'+'_rollback.py'):
            with self.subTest(name=name),self.assertRaises(RuntimeError):export.scan(name,b'{}')
    def test_tampered_export_and_extra_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(export,'files_at',return_value=('a'*40,self.files())):
            root=Path(tmp)/'tree';export.export('main',root)
            (root/'install.sh').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'TREE_CHANGED'):export.verify(root)
            (root/'install.sh').write_bytes(self.files()['install.sh'][1])
            (root/'extra').write_text('extra')
            with self.assertRaisesRegex(RuntimeError,'TREE_FILE_SET'):export.verify(root)
    def test_documentation_and_loopback_addresses_allowed(self):
        export.scan('example.json',b'{"lan":"192.0.2.1", "listen":"127.0.0.1"}')
