"""Fixed-scope checks for the v0.3.1 management-only update."""
import hashlib
import json
import unittest
from unittest.mock import patch

from scripts.release_management_upgrade import (BOUNDED, EXTERNAL_DNS_UNITS,
    PRESERVED, WEB_UNIT, management_payload, plan, start_management,
    stop_management, verify_external_dns, verify_installed_dns)


class ManagementUpgradePlanTests(unittest.TestCase):
    def setUp(self):
        self.files = {}
        self.previous = {}
        for path, pin in BOUNDED['files'].items():
            self.files[path] = (b'candidate:' + path.encode(), 0o644)
            if pin is not None:
                self.previous[path] = {'sha256': pin, 'mode': 0o644}
        self.unmodified = '/opt/bridge-official/dae'
        body = b'official-pinned'
        self.files[self.unmodified] = (body, 0o555)
        self.previous[self.unmodified] = {'sha256': hashlib.sha256(body).hexdigest(), 'mode': 0o555}

    def test_exact_management_diff(self):
        desired, changed = plan({'files': self.previous}, self.files)
        self.assertEqual(changed, set(BOUNDED['files']))
        self.assertEqual(desired[self.unmodified], self.previous[self.unmodified])

    def test_baseline_hash_change_rejected(self):
        old = json.loads(json.dumps(self.previous))
        path = next(p for p, pin in BOUNDED['files'].items() if pin is not None)
        old[path]['sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'MANAGEMENT_BASELINE_MISMATCH'):
            plan({'files': old}, self.files)

    def test_official_or_dns_change_rejected(self):
        files = dict(self.files)
        files[self.unmodified] = (b'changed-official', 0o555)
        with self.assertRaisesRegex(RuntimeError, 'MANAGEMENT_SCOPE_CHANGED'):
            plan({'files': self.previous}, files)

    def test_unexpected_file_and_missing_contract_rejected(self):
        files = dict(self.files)
        files['/etc/systemd/system/dae.service'] = (b'changed-unit', 0o644)
        with self.assertRaisesRegex(RuntimeError, 'MANAGEMENT_FILE_SET'):
            plan({'files': self.previous}, files)
        files = dict(self.files)
        del files['/opt/bridge/contracts/m4/extension-record-v1.json']
        with self.assertRaisesRegex(RuntimeError, 'MANAGEMENT_FILE_SET'):
            plan({'files': self.previous}, files)

    def test_wrong_permissions_rejected(self):
        files = dict(self.files)
        path = '/opt/bridge/bridge_m4/upstream_contracts.py'
        files[path] = (files[path][0], 0o666)
        with self.assertRaisesRegex(RuntimeError, 'MANAGEMENT_CANDIDATE_MISSING'):
            plan({'files': self.previous}, files)

    def test_clean_install_uses_packaged_dns_check(self):
        with patch('scripts.release_health.check') as packaged, patch(
                'scripts.release_management_upgrade.verify_external_dns') as inherited:
            verify_installed_dns({'files': {'/etc/systemd/system/bridge-lan-dns.service': {}}})
        packaged.assert_called_once_with()
        inherited.assert_not_called()

    def test_existing_production_uses_inherited_dns_check(self):
        with patch('scripts.release_health.check') as packaged, patch(
                'scripts.release_management_upgrade.verify_external_dns') as inherited:
            verify_installed_dns({'files': {}})
        inherited.assert_called_once_with()
        packaged.assert_not_called()

    def test_existing_dns_reads_real_backend_and_four_protocol_paths(self):
        status={'state':'running','identityVerified':True,'configSha256':'abc'}
        with patch('bridge_m4.dns_sync_runtime.read_status',return_value=(status,'abc')), patch(
                'bridge_m4.dns_sync_runtime.Backends') as backends, patch(
                'bridge_m4.dns_sync.decide',return_value={'consistent':True}), patch(
                'pathlib.Path.read_text',return_value='setLocal("192.0.2.1:53")\n'), patch(
                'scripts.release_health.dns') as query:
            backends.return_value.states.return_value={'DAE':'UP','DIRECT':'DOWN'}
            verify_external_dns()
        self.assertEqual([call.args[:3] for call in query.call_args_list],
                         [('192.0.2.1',53,'www.baidu.com')]*2+
                         [('127.0.0.1',5353,'www.baidu.com')]*2)
        self.assertEqual([call.args[3] for call in query.call_args_list],
                         [False,True,False,True])

    def test_existing_dns_refuses_ambiguous_listener(self):
        status={'state':'running','identityVerified':True,'configSha256':'abc'}
        with patch('bridge_m4.dns_sync_runtime.read_status',return_value=(status,'abc')), patch(
                'bridge_m4.dns_sync_runtime.Backends') as backends, patch(
                'bridge_m4.dns_sync.decide',return_value={'consistent':True}), patch(
                'pathlib.Path.read_text',return_value='setLocal("0.0.0.0:53")\naddLocal("192.0.2.1:53")\n'):
            backends.return_value.states.return_value={'DAE':'UP','DIRECT':'DOWN'}
            # Broad listeners do not identify the existing LAN endpoint.
            with self.assertRaisesRegex(RuntimeError,'DNS_LISTENER_IDENTITY'):
                verify_external_dns()

    def test_dashboard_follows_graphql_management_restart(self):
        self.assertNotIn(WEB_UNIT, PRESERVED)
        with patch('scripts.release_management_upgrade.ctl') as ctl, patch(
                'scripts.release_management_upgrade.show', return_value={'ActiveState':'inactive'}), patch(
                'scripts.release_management_upgrade.verify_management') as ready, patch(
                'scripts.release_management_upgrade.wait_sync_idle') as idle:
            stop_management()
            start_management()
        calls=[call.args for call in ctl.call_args_list]
        self.assertIn(('stop',WEB_UNIT),calls)
        self.assertIn(('start',WEB_UNIT),calls)
        self.assertLess(calls.index(('stop',WEB_UNIT)),
                        next(i for i,c in enumerate(calls) if c[0]=='stop' and 'bridge-graphql.service' in c))
        self.assertGreater(calls.index(('start',WEB_UNIT)),
                           next(i for i,c in enumerate(calls) if c[0]=='start' and 'bridge-graphql.service' in c))
        ready.assert_called_once_with()
        idle.assert_called_once_with()
        self.assertGreater(calls.index(('start',*('independent-dns-sync.timer',
                         'independent-policy-sync.timer'))),calls.index(('start',WEB_UNIT)))

    def test_external_dns_units_stay_out_of_management_manifest(self):
        full=dict(self.files)
        full.update({name:(b'external-dns',0o644) for name in EXTERNAL_DNS_UNITS})
        with patch('scripts.release_lifecycle.ready_payload',return_value=full):
            selected=management_payload({'files':self.previous})
        desired,changed=plan({'files':self.previous},selected)
        self.assertEqual(changed,set(BOUNDED['files']))
        self.assertEqual(set(desired),set(self.previous)|{n for n,p in BOUNDED['files'].items() if p is None})
        self.assertFalse(set(desired)&EXTERNAL_DNS_UNITS)

    def test_existing_dns_unit_remains_owned_and_unchanged(self):
        name=next(iter(sorted(EXTERNAL_DNS_UNITS)))
        full=dict(self.files)
        full.update({unit:(b'dns-original',0o644) for unit in EXTERNAL_DNS_UNITS})
        old=dict(self.previous);old[name]={'sha256':hashlib.sha256(b'dns-original').hexdigest(),'mode':0o644}
        with patch('scripts.release_lifecycle.ready_payload',return_value=full):
            selected=management_payload({'files':old})
        desired,_=plan({'files':old},selected)
        self.assertEqual(desired[name],old[name])
        full[name]=(b'dns-changed',0o644)
        with patch('scripts.release_lifecycle.ready_payload',return_value=full):
            selected=management_payload({'files':old})
        with self.assertRaisesRegex(RuntimeError,'MANAGEMENT_SCOPE_CHANGED'):
            plan({'files':old},selected)

    def test_unexpected_extra_file_still_fails_before_service_stop(self):
        full=dict(self.files)
        full.update({name:(b'external-dns',0o644) for name in EXTERNAL_DNS_UNITS})
        full['/etc/systemd/system/unexpected.service']=(b'unexpected',0o644)
        with patch('scripts.release_lifecycle.ready_payload',return_value=full):
            with self.assertRaisesRegex(RuntimeError,'MANAGEMENT_FILE_SET'):
                management_payload({'files':self.previous})
