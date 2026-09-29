"""Regression tests for the production policy-sync identity-only path."""
import ast
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO


SOURCE = Path(__file__).resolve().parents[2] / 'deployment/m4/production/sync_policy_independent.py'
TREE = ast.parse(SOURCE.read_text())
FUNCTIONS = ast.Module(body=[node for node in TREE.body if isinstance(node, ast.FunctionDef)
                             and node.name in {'identity_action', 'refresh_identity_atomically',
                                               'reconcile_identity'}],
                       type_ignores=[])
SCOPE = {'json': json, 'os': os, 'tempfile': tempfile, 'time': time}
exec(compile(FUNCTIONS, str(SOURCE), 'exec'), SCOPE)
identity_action = SCOPE['identity_action']
refresh_identity_atomically = SCOPE['refresh_identity_atomically']
reconcile_identity = SCOPE['reconcile_identity']


class PolicyIdentityRefreshTests(unittest.TestCase):
    def setUp(self):
        self.old = {'fingerprint': 'a' * 64, 'activeBundle': 'b' * 64,
                    'configSha256': 'c' * 64, 'source': 'INDEPENDENT_BRIDGE',
                    'generation': 'retained-generation', 'applied_at': 123}

    def test_identical_identity_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'independent-sync.json'
            path.write_text(json.dumps(self.old))
            before = (path.read_bytes(), path.stat().st_ino)
            def unexpected_read():
                self.fail('unchanged identity must not re-read status')
            self.assertTrue(reconcile_identity(self.old, 'a' * 64, 'b' * 64,
                                               'c' * 64, path, unexpected_read))
            self.assertEqual((path.read_bytes(), path.stat().st_ino), before)

    def test_same_fingerprint_new_bundle_only_refreshes_identity(self):
        self.check_refresh('d' * 64, 'c' * 64)

    def test_same_fingerprint_new_config_hash_only_refreshes_identity(self):
        self.check_refresh('b' * 64, 'e' * 64)

    def check_refresh(self, bundle_id, config_sha256):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'independent-sync.json'
            path.write_text(json.dumps(self.old))
            before_inode = path.stat().st_ino
            status = lambda: ({'state': 'running', 'identityVerified': True,
                               'activeBundle': bundle_id, 'configSha256': config_sha256},
                              config_sha256)
            output = StringIO()
            with redirect_stdout(output):
                self.assertTrue(reconcile_identity(self.old, 'a' * 64, bundle_id,
                                                   config_sha256, path, status))
            self.assertIn('IDENTITY_REFRESHED=true RELOAD=false', output.getvalue())
            current = json.loads(path.read_text())
            self.assertEqual(current['activeBundle'], bundle_id)
            self.assertEqual(current['configSha256'], config_sha256)
            for key in ('fingerprint', 'generation', 'applied_at', 'source'):
                self.assertEqual(current[key], self.old[key])
            self.assertGreater(current['verified_at'], 0)
            self.assertNotEqual(path.stat().st_ino, before_inode)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_changed_fingerprint_keeps_full_sync_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'independent-sync.json'
            path.write_text(json.dumps(self.old))
            def unexpected_read():
                self.fail('full sync must continue to its existing generation path')
            for bundle, config in [('b' * 64, 'c' * 64), ('d' * 64, 'e' * 64)]:
                self.assertFalse(reconcile_identity(self.old, 'f' * 64, bundle,
                                                    config, path, unexpected_read))
            self.assertEqual(json.loads(path.read_text()), self.old)

    def test_stale_status_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'independent-sync.json'
            path.write_text(json.dumps(self.old))
            with self.assertRaisesRegex(SystemExit, 'Independent source changed'):
                reconcile_identity(self.old, 'a' * 64, 'd' * 64, 'c' * 64, path,
                                   lambda: ({'state': 'stopped', 'identityVerified': False},
                                            'c' * 64))
            self.assertEqual(json.loads(path.read_text()), self.old)


if __name__ == '__main__':
    unittest.main()
