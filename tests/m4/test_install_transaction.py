import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import m4_install_transaction as tx

class InstallTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.root.chmod(0o700)
    def test_atomic_replacement_and_mode(self):
        path=self.root/'installed';path.write_bytes(b'old')
        tx.write(path,b'new',0o644)
        self.assertEqual(path.read_bytes(),b'new')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o644)
        self.assertFalse(path.with_name('installed.restore-new').exists())
    def test_interrupted_replace_preserves_original(self):
        path=self.root/'installed';path.write_bytes(b'old')
        with patch.object(tx.os,'replace',side_effect=OSError('synthetic interruption')):
            with self.assertRaises(OSError):tx.write(path,b'new',0o644)
        self.assertEqual(path.read_bytes(),b'old')
        self.assertEqual(path.with_name('installed.restore-new').read_bytes(),b'new')
    def test_stale_symlink_rejected(self):
        path=self.root/'installed';victim=self.root/'victim';victim.write_bytes(b'keep')
        path.with_name('installed.restore-new').symlink_to(victim)
        with self.assertRaisesRegex(RuntimeError,'MANUAL_INTERVENTION'):tx.write(path,b'new',0o644)
        self.assertEqual(victim.read_bytes(),b'keep')
    def test_concurrent_installer_rejected(self):
        # Ownership is mocked only for this non-root host test; flock is real.
        directory=SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=0,st_gid=0)
        lock=SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=0,st_gid=0,st_nlink=1)
        with patch.object(tx,'ROOT',self.root),patch.object(Path,'lstat',return_value=directory),patch.object(os,'fstat',return_value=lock):
            with tx.exclusive():
                with self.assertRaisesRegex(RuntimeError,'INSTALL_BUSY'):
                    with tx.exclusive():self.fail('second installer entered')
            with tx.exclusive():pass

    def test_policy_script_is_optional_exact_path(self):
        name='/etc/dae-dns-repair/sync_policy_independent.py'
        self.assertTrue(tx.allowed(name))
        self.assertNotIn(name,tx.EXACT)
        self.assertFalse(tx.allowed('/etc/dae-dns-repair/other.py'))
        self.assertFalse(tx.allowed(name+'.bak'))
