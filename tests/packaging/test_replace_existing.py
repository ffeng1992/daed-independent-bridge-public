import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import release_replace


class ReplaceExistingTests(unittest.TestCase):
    def test_candidate_only_changes_management_files(self):
        # No production data is embedded in this fixture. Its shape models the
        # verified 830-file installation and the candidate's exact delta.
        files = {f'/opt/bridge/vendor/synthetic-{n}': (b'same', 0o644)
                 for n in range(829 - len(release_replace.CHANGED))}
        files.update({name: (b'new', 0o644) for name in release_replace.CHANGED | release_replace.ADDED})
        unit = release_replace.ROOT / 'deployment/release/units/daed-web.service'
        files['/etc/systemd/system/daed-web.service'] = (unit.read_bytes(), 0o644)
        old = {name: {'sha256': release_replace.sha(body), 'mode': mode}
               for name, (body, mode) in files.items() if name not in release_replace.ADDED}
        old.update({name: {'sha256': release_replace.sha(b'old'), 'mode': 0o644}
                    for name in release_replace.CHANGED})
        self.assertEqual(len(old), 830)
        with patch.object(release_replace, 'prepare'), \
             patch.object(release_replace.m4_install, 'payload', return_value=files), \
             patch.object(release_replace, 'frontend_payload', return_value={}):
            result, desired = release_replace.payload_and_manifest({'files': old})
            self.assertEqual(result, files)
            self.assertEqual(len(desired), 834)
            bad = dict(old)
            bad['/opt/bridge/vendor/synthetic-0'] = {'sha256': release_replace.sha(b'drift'), 'mode': 0o644}
            with self.assertRaisesRegex(RuntimeError, 'CANDIDATE_DIFF_UNEXPECTED'):
                release_replace.payload_and_manifest({'files': bad})

    def test_staged_bytes_and_modes_are_hash_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            files = {name: (name.encode(), 0o644) for name in release_replace.CHANGED | release_replace.ADDED}
            desired = {name: {'sha256': release_replace.sha(body), 'mode': mode}
                       for name, (body, mode) in files.items()}
            result = release_replace.stage(files, desired, Path(temp))
            self.assertEqual(len(list(result.iterdir())), len(files))
            first = next(iter(desired))
            desired[first]['sha256'] = '0' * 64
            with tempfile.TemporaryDirectory() as other:
                with self.assertRaisesRegex(RuntimeError, 'STAGED_HASH'):
                    release_replace.stage(files, desired, Path(other))

    def test_install_dispatch_is_explicit(self):
        source = (Path(__file__).resolve().parents[2] / 'install.sh').read_text()
        self.assertIn('"--replace-existing"', source)
        self.assertIn('scripts.release_replace', source)
        self.assertNotIn('scripts.release_dns', source)

    def test_complete_database_backups_use_new_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / 'source.sqlite'
            connection = sqlite3.connect(database)
            connection.execute('create table value (id integer primary key, text_value text)')
            connection.execute('insert into value values (1, ?)', ('synthetic',))
            connection.commit()
            connection.close()
            with patch.object(release_replace, 'DB', database):
                first = release_replace.database_snapshot(root)
                second = release_replace.database_snapshot(root)
            self.assertEqual(first, second)
            self.assertEqual(len(list(root.glob('database-check-*.sqlite'))), 2)


if __name__ == '__main__':
    unittest.main()
