"""Isolated filesystem + fake upstream tests. Never contacts GitHub or DAE."""
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

RELEASE = pathlib.Path(__file__).resolve().parents[2]
from bridge_m4 import geodata
from scripts import release_geodata_update as updater


class LocalServer:
    def __init__(self, data, *, bad_sum=False, bad_payload=None):
        self.data = dict(data)
        self.requests = []
        self.bad_sum = bad_sum
        self.bad_payload = bad_payload

    def get(self, url, cap):
        self.requests.append(url)
        for name, (repository, remote) in updater.SOURCES.items():
            tag = '20261021011254' if name == 'geosite.dat' else '202610050438'
            root = f'https://github.com/{repository}/releases/download/{tag}/'
            if url == f'https://api.github.com/repos/{repository}/releases/latest':
                assets = [
                    {'name': n, 'browser_download_url': root + n}
                    for n in (remote, remote + '.sha256sum')
                ]
                return json.dumps({'tag_name': tag, 'assets': assets}).encode()
            if url == root + remote + '.sha256sum':
                h = hashlib.sha256(self.data[name]).hexdigest()
                if self.bad_sum:
                    return (h + '  WRONG_NAME.dat\n').encode()
                return (h + '  ' + remote + '\n').encode()
            if url == root + remote:
                return self.bad_payload if self.bad_payload is not None else self.data[name]
        raise RuntimeError('UNKNOWN_TEST_URL')


class DataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.root = self.base / 'geodata'
        self.original = self.base / 'original'
        self.original.mkdir(mode=0o700)
        self.old = {'geosite.dat': b'old-geosite-data', 'geoip.dat': b'old-geoip-data'}
        for name, contents in self.old.items():
            target = self.original / name
            target.write_bytes(contents)
            target.chmod(0o444)
        self.owner = os.geteuid()
        self.pre_status = {'state': 'running', 'identityVerified': True,
                           'activeBundle': 'synthetic-bundle', 'configSha256': 'ab' * 32,
                           'InvocationID': 'previous', 'MainPID': 100}
        self.checks, self.validations, self.restarts = [], [], []
        self.remote = dict(self.old)
        self.server = LocalServer(self.remote)
        # This fixture represents a previously confirmed NO_CHANGE check of the
        # exact manually installed baseline. Subsequent tag changes are safe.
        self.root.mkdir(mode=0o700)
        marker = {'result': 'NO_CHANGE', 'assets': {
            name: hashlib.sha256(data).hexdigest() for name,data in self.old.items()}}
        (self.root/'last-check.json').write_text(json.dumps(marker))
        (self.root/'last-check.json').chmod(0o644)

    def health(self):
        self.checks.append(True)
        return dict(self.pre_status)

    def validator(self, location):
        self.validations.append(location)
        self.assertTrue((location / 'geosite.dat').exists())
        self.assertTrue((location / 'geoip.dat').exists())

    def restart(self, original, folder):
        self.restarts.append((original, folder))
        self.assertEqual(original, self.pre_status)
        self.assertEqual(geodata.selected_dir(self.root, self.original, uid=self.owner), folder)

    def update(self, *, validator=None, restart=None, server=None):
        return updater.once(root=self.root, official=self.original, owner=self.owner,
                            client=server or self.server,
                            check_health=self.health,
                            validate_stage=validator or self.validator,
                            restart=restart or self.restart,
                            update_record=False)

    def test_no_change_never_downloads_or_restarts(self):
        value = self.update()
        self.assertEqual(value['result'], 'NO_CHANGE')
        self.assertFalse(self.validations)
        self.assertFalse(self.restarts)
        self.assertFalse(self.root.joinpath('current').exists())
        self.assertEqual(len(self.server.requests), 4)
        self.assertFalse(any(v.endswith('.dat') for v in self.server.requests))

    def test_first_manual_release_updates_without_prior_no_change(self):
        (self.root / 'last-check.json').unlink()
        self.remote['geoip.dat'] = b'new-ip'
        self.server = LocalServer(self.remote)
        output = self.update()
        self.assertEqual(output['result'], 'UPDATED')
        self.assertIsNotNone(geodata.current_id(self.root))
        self.assertEqual(len(self.restarts), 1)
        self.assertEqual(len(self.validations), 1)
        self.assertEqual((self.original / 'geoip.dat').read_bytes(), self.old['geoip.dat'])

    def test_only_changed_file_downloaded_and_both_data_verified(self):
        self.remote['geosite.dat'] = b'new-domain-list-data'
        self.server = LocalServer(self.remote)
        value = self.update()
        self.assertEqual(value['result'], 'UPDATED')
        self.assertEqual(value['changed'], ['geosite.dat'])
        self.assertEqual(len(self.restarts), 1)
        self.assertEqual(len(self.validations), 1)
        self.assertEqual(len(self.server.requests), 5)
        selected = geodata.selected_dir(self.root, self.original, uid=self.owner)
        self.assertEqual((selected / 'geosite.dat').read_bytes(), self.remote['geosite.dat'])
        self.assertEqual((selected / 'geoip.dat').read_bytes(), self.old['geoip.dat'])
        self.assertTrue((selected / 'manifest.json').exists())

    def test_both_changed_get_one_restart(self):
        self.remote = {'geosite.dat': b'new-site', 'geoip.dat': b'new-ip'}
        self.server = LocalServer(self.remote)
        result = self.update()
        self.assertEqual(result['result'], 'UPDATED')
        self.assertEqual(len(result['changed']), 2)
        self.assertEqual(len(self.restarts), 1)
        self.assertEqual(len(self.server.requests), 6)

    def test_incorrect_checksum_never_changes_live_pointer(self):
        self.remote['geoip.dat'] = b'something-changed'
        self.server = LocalServer(self.remote, bad_payload=b'fake-corrupt-geoip')
        value = self.update()
        self.assertEqual(value['result'], 'CHECK_FAILED')
        self.assertEqual(value['error'], 'GEODATA_UPSTREAM_SHA256_MISMATCH')
        self.assertEqual(geodata.selected_dir(self.root, self.original, uid=self.owner), self.original)
        self.assertFalse(self.restarts)

    def test_malformed_sha_record_rejected_before_download(self):
        self.server = LocalServer(self.remote, bad_sum=True)
        value = self.update()
        self.assertEqual(value['result'], 'CHECK_FAILED')
        self.assertEqual(value['error'], 'GEODATA_SHA256_FORMAT')
        self.assertFalse(self.restarts)
        self.assertFalse(any(v.endswith('.dat') for v in self.server.requests))

    def test_validator_failure_does_not_restart_or_switch(self):
        self.remote['geoip.dat'] = b'new-ip'
        self.server = LocalServer(self.remote)
        def fail(_):
            raise RuntimeError('VALIDATE_FAILED')
        value = self.update(validator=fail)
        self.assertEqual(value['result'], 'CHECK_FAILED')
        self.assertEqual(value['error'], 'VALIDATE_FAILED')
        self.assertFalse(self.restarts)
        self.assertEqual(geodata.current_id(self.root), None)

    def test_restart_failure_rolls_back_original(self):
        self.remote['geoip.dat'] = b'new-ip'
        self.server = LocalServer(self.remote)
        calls = []
        def fail_first(before, folder):
            calls.append(folder)
            if len(calls) == 1:
                raise RuntimeError('RESTART_FAILED')
            self.assertEqual(folder, self.original)
        value = self.update(restart=fail_first)
        self.assertEqual(value['result'], 'ROLLED_BACK')
        self.assertEqual(value['error'], 'RESTART_FAILED')
        self.assertEqual(calls[1], self.original)
        self.assertEqual(geodata.current_id(self.root), None)

    def test_failed_recovery_is_never_reported_as_success(self):
        self.remote['geoip.dat'] = b'new-ip'
        self.server = LocalServer(self.remote)
        def bad(*_):
            raise RuntimeError('RESTART_FAILED')
        value = self.update(restart=bad)
        self.assertEqual(value['result'], 'ROLLBACK_FAILED')
        self.assertIsNotNone(value['rollbackError'])

    def test_tampered_active_file_is_rejected_not_fallback(self):
        self.remote['geoip.dat'] = b'new-ip'
        self.server = LocalServer(self.remote)
        self.assertEqual(self.update()['result'], 'UPDATED')
        folder = geodata.selected_dir(self.root, self.original, uid=self.owner)
        (folder / 'geoip.dat').chmod(0o644)
        (folder / 'geoip.dat').write_bytes(b'corrupted')
        with self.assertRaisesRegex(RuntimeError, 'GEODATA_FILE_HASH'):
            geodata.generation(self.root, uid=self.owner)

    def test_pointer_traversal_rejected(self):
        updater.provision(self.root, uid=self.owner)
        os.symlink('../private', self.root / 'current')
        with self.assertRaisesRegex(RuntimeError, 'GEODATA_POINTER_TARGET'):
            geodata.generation(self.root, uid=self.owner)

    def test_external_asset_domain_is_rejected(self):
        client = LocalServer(self.remote)
        real_get = client.get
        def hijack(url, cap):
            data = real_get(url, cap)
            if url.endswith('/releases/latest'):
                record = json.loads(data)
                record['assets'][0]['browser_download_url'] = 'https://evil.example/bad.dat'
                return json.dumps(record).encode()
            return data
        client.get = hijack
        value = self.update(server=client)
        self.assertEqual(value['result'], 'CHECK_FAILED')
        self.assertEqual(value['error'], 'GEODATA_RELEASE_PROVENANCE')

    def test_second_check_after_update_avoids_all_dat_downloads(self):
        self.remote['geosite.dat'] = b'another-new-site'
        self.server = LocalServer(self.remote)
        self.assertEqual(self.update()['result'], 'UPDATED')
        later = LocalServer(self.remote)
        value = self.update(server=later)
        self.assertEqual(value['result'], 'NO_CHANGE')
        self.assertEqual(len(self.restarts), 1)
        self.assertEqual(len(later.requests), 4)


class RuntimeIntegrationTests(unittest.TestCase):
    def test_dynamic_validation_ignores_old_release_pins(self):
        from bridge_m4 import validation
        folder = pathlib.Path('/isolated/new-generation')
        pins = {'geoip.dat':'new-ip','geosite.dat':'new-site'}
        with mock.patch.object(validation,'asset_identity',side_effect=RuntimeError('OLD_RELEASE_MISMATCH')) as old, mock.patch.object(geodata,'verify_generation_folder',return_value=(folder,{})), mock.patch.object(geodata,'selected_hashes_from_folder',return_value=pins), mock.patch.object(pathlib.Path,'read_bytes',return_value=b'official'), mock.patch.object(validation.subprocess,'run',return_value=mock.Mock(returncode=0)) as run:
            result=validation.validate(pathlib.Path('/candidate.dae'),hashlib.sha256(b'official').hexdigest(),assets_override=folder)
            self.assertEqual(result['assetSha256'],pins)
            self.assertEqual(run.call_args.kwargs['env']['DAE_LOCATION_ASSET'],str(folder))
            old.assert_not_called()

    def test_static_environment_still_requires_old_release_identity(self):
        from bridge_m4 import validation
        with mock.patch.object(geodata,'selected_dir',return_value=validation.ASSETS), mock.patch.object(validation,'asset_identity',side_effect=RuntimeError('OLD_RELEASE_MISMATCH')):
            with self.assertRaisesRegex(RuntimeError,'OLD_RELEASE_MISMATCH'):
                validation.runtime_asset_env()
            with self.assertRaisesRegex(RuntimeError,'OLD_RELEASE_MISMATCH'):
                validation.verified_selected_hashes()

    def test_retired_policy_dns_does_not_require_release_configuration(self):
        response = mock.Mock(stdout='inactive\n')
        with mock.patch.object(updater.subprocess, 'run', return_value=response):
            self.assertFalse(updater.policy_dns_active())

    def test_active_policy_dns_remains_checked(self):
        with mock.patch.object(updater.subprocess, 'run', return_value=mock.Mock(stdout='active\n')):
            self.assertTrue(updater.policy_dns_active())

    def test_unknown_or_transitioning_policy_dns_fails_closed(self):
        for state in ('activating', 'failed', 'unexpected'):
            with self.subTest(state=state), mock.patch.object(updater.subprocess, 'run',
                    return_value=mock.Mock(stdout=state+'\n')):
                with self.assertRaises(RuntimeError):
                    updater.policy_dns_active()

    def test_updater_in_release_install_and_lifecycle(self):
        from scripts import release_payload, release_lifecycle
        # Frontend archive availability is unrelated to the updater payload.
        with mock.patch("scripts.release_frontend.payload", return_value={}):
            files = release_payload.payload(RELEASE)
        self.assertIn('/opt/bridge/scripts/release_geodata_update.py', files)
        self.assertIn('/usr/local/bin/bridge-geodata-update', files)
        for suffix in ('service','timer'):
            self.assertIn('/etc/systemd/system/bridge-geodata-update.'+suffix, files)
        unit = files['/etc/systemd/system/bridge-geodata-update.service'][0].decode()
        self.assertNotIn('User=root', unit)
        self.assertIn('NoNewPrivileges=yes', unit)
        self.assertIn('ProtectSystem=strict', unit)
        self.assertIn('bridge-geodata-update.timer', release_lifecycle.TIMERS)
        self.assertIn('bridge-geodata-update.service', release_lifecycle.STOP)

    def test_validator_keeps_original_asset_identity(self):
        import ast
        old = """def asset_identity():
    pins={p['path']:p for p in DAE_ARTIFACT['archive_members']}
    observed={}
    for name in ('geoip.dat','geosite.dat'):
        body=(ASSETS/name).read_bytes();observed[name]=digest(body)
        check(len(body)==pins[name]['size'] and observed[name]==pins[name]['sha256'],'OFFICIAL_ASSET_HASH')
    return observed
"""
        new = (RELEASE/'bridge_m4/validation.py').read_text()
        function = lambda body: next(n for n in ast.parse(body).body
                                    if isinstance(n,ast.FunctionDef) and n.name=='asset_identity')
        self.assertEqual(ast.dump(function(old),include_attributes=False),
                         ast.dump(function(new),include_attributes=False))

class CommandResultTests(unittest.TestCase):
    def test_restored_update_is_not_reported_as_success(self):
        from contextlib import nullcontext
        for result, expected in (("NO_CHANGE", 0), ("UPDATED", 0),
                                 ("ROLLED_BACK", 1), ("ROLLBACK_FAILED", 1),
                                 ("CHECK_FAILED", 1)):
            with self.subTest(result=result), mock.patch.object(updater.os, "geteuid", return_value=0), \
                 mock.patch.object(updater, "exclusive", return_value=nullcontext()), \
                 mock.patch.object(updater, "once", return_value={"result": result}), \
                 mock.patch("builtins.print"):
                self.assertEqual(updater.main(["check"]), expected)

    def test_busy_lock_descriptor_is_closed(self):
        with mock.patch.object(updater.os, "open", return_value=77), \
             mock.patch.object(updater.os, "fstat", return_value=mock.Mock(st_uid=0, st_nlink=1, st_mode=0o600)), \
             mock.patch.object(updater.fcntl, "flock", side_effect=BlockingIOError), \
             mock.patch.object(updater.os, "close") as close:
            with self.assertRaisesRegex(RuntimeError, "GEODATA_UPDATE_BUSY"):
                with updater.exclusive((pathlib.Path("/synthetic-lock"),)):
                    self.fail("busy lock acquired")
            close.assert_called_once_with(77)


if __name__ == '__main__':
    unittest.main()
