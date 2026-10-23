"""R4 not-found regression and negative cases; no real systemd is controlled.

The five-field missing-service observation is transcribed from the R4 review,
not captured here. These tests exercise the real parser/predicate with substitutes.
"""
import copy
import subprocess
import types
import unittest
from unittest.mock import patch

from bridge_m4 import deployment_profile as profile
from scripts import release_native_lifecycle as native

ABSENT = {'LoadState': 'not-found', 'ActiveState': 'inactive', 'MainPID': '0',
          'ControlPID': '0', 'UnitFileState': ''}
NATIVE = {'schemaVersion': 1, 'layoutVersion': 1, 'dnsOwnership': 'native-dae',
          'policyDnsUnits': []}


def states(observed=ABSENT):
    return {name: copy.deepcopy(observed) for name in profile.POLICY_UNITS}


def raw(observed):
    return ''.join(k + '=' + v + '\n' for k, v in observed.items())


class DnsPresenceTests(unittest.TestCase):
    def test_review_report_exact_missing_unit_observation_is_accepted(self):
        self.assertFalse(profile.selected_policy_dns(NATIVE, states()))

    def test_real_show_parser_requests_loadstate_and_empty_properties(self):
        with patch.object(profile.subprocess, 'run', return_value=types.SimpleNamespace(stdout=raw(ABSENT))) as run:
            self.assertEqual(profile.show(profile.POLICY_UNITS[0]), ABSENT)
        command = run.call_args.args[0]
        self.assertIn('--all', command)
        self.assertIn('--property=LoadState,ActiveState,MainPID,ControlPID,UnitFileState', command)
        self.assertTrue(run.call_args.kwargs['check'])
        self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_actual_policy_dns_active_call_chain_accepts_report_observation(self):
        with patch.object(profile, 'load', return_value=NATIVE), \
             patch.object(profile.subprocess, 'run', return_value=types.SimpleNamespace(stdout=raw(ABSENT))) as run:
            self.assertFalse(profile.policy_dns_active())
        self.assertEqual([c.args[0][2] for c in run.call_args_list], list(profile.POLICY_UNITS))
        self.assertTrue(all(c.args[0][1] == 'show' for c in run.call_args_list))

    def test_native_preflight_and_health_use_same_predicate(self):
        with patch.object(native, 'observe', return_value=copy.deepcopy(ABSENT)), \
             patch.object(native, 'ctl') as control:
            native.verify_retired()
        self.assertIs(native.retired_policy_dns, profile.retired_policy_dns)
        self.assertFalse(profile.selected_policy_dns(NATIVE, states()))
        control.assert_not_called()

    def test_native_observe_keeps_empty_properties(self):
        with patch.object(native, 'ctl', return_value=types.SimpleNamespace(stdout=raw(ABSENT))) as ctl:
            self.assertEqual(native.observe(profile.POLICY_UNITS[0]), ABSENT)
        self.assertIn('--all', ctl.call_args.args)

    def test_missing_loadstate_is_not_missing_unit(self):
        value = dict(ABSENT); value.pop('LoadState')
        self.assertFalse(profile.retired_policy_dns(value))
        with self.assertRaisesRegex(RuntimeError, 'UNDECLARED'):
            profile.selected_policy_dns(NATIVE, states(value))

    def test_missing_pid_or_empty_enable_field_is_not_zero_or_empty(self):
        for key in ('MainPID', 'ControlPID', 'UnitFileState', 'ActiveState'):
            value = dict(ABSENT); value.pop(key)
            with self.subTest(key=key):
                self.assertFalse(profile.retired_policy_dns(value))
                with self.assertRaises(RuntimeError):
                    profile.selected_policy_dns(NATIVE, states(value))

    def test_not_found_in_unit_file_state_does_not_replace_load_state(self):
        for load in ('loaded', '', 'unknown', 'error', 'bad-setting', 'merged'):
            value = dict(ABSENT, LoadState=load, UnitFileState='not-found')
            with self.subTest(load=load), self.assertRaises(RuntimeError):
                profile.selected_policy_dns(NATIVE, states(value))

    def test_loaded_empty_unit_file_state_is_unknown_not_retired(self):
        with self.assertRaisesRegex(RuntimeError, 'UNDECLARED'):
            profile.selected_policy_dns(NATIVE, states(dict(ABSENT, LoadState='loaded')))

    def test_missing_unit_with_live_or_transition_state_is_rejected(self):
        for state in ('active', 'activating', 'deactivating', 'failed', 'reloading', 'refreshing', '', 'unknown'):
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                profile.selected_policy_dns(NATIVE, states(dict(ABSENT, ActiveState=state)))

    def test_missing_unit_with_any_process_is_rejected(self):
        for field in ('MainPID', 'ControlPID'):
            for value in ('1', '88', '', '-1', '00', 0, None):
                observed = dict(ABSENT); observed[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                    profile.selected_policy_dns(NATIVE, states(observed))

    def test_missing_unit_with_enable_claim_is_rejected(self):
        for state in ('enabled', 'enabled-runtime', 'linked', 'linked-runtime', 'alias', 'static', 'disabled', 'masked', 'not-found'):
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                profile.selected_policy_dns(NATIVE, states(dict(ABSENT, UnitFileState=state)))

    def test_loaded_enabled_unit_is_not_retired(self):
        for state in ('enabled', 'enabled-runtime', 'linked', 'linked-runtime', 'alias', 'generated', 'indirect', '', 'unknown'):
            value = dict(ABSENT, LoadState='loaded', UnitFileState=state)
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                profile.selected_policy_dns(NATIVE, states(value))

    def test_disabled_masked_static_inactive_units_remain_accepted(self):
        for load, enable in (('loaded', 'disabled'), ('masked', 'masked'), ('loaded', 'static')):
            for active in ('inactive', 'failed'):
                value = dict(ABSENT, LoadState=load, UnitFileState=enable, ActiveState=active)
                with self.subTest(load=load, enable=enable, active=active):
                    self.assertFalse(profile.selected_policy_dns(NATIVE, states(value)))
                    with patch.object(native, 'observe', return_value=value):
                        native.verify_retired()

    def test_selected_missing_consumer_is_never_treated_as_retired(self):
        for ownership, unit in (('bridge-managed', profile.POLICY_UNITS[0]),
                                ('external-policy', profile.POLICY_UNITS[1])):
            selected = dict(NATIVE, dnsOwnership=ownership, policyDnsUnits=[unit])
            with self.subTest(ownership=ownership), self.assertRaisesRegex(RuntimeError, 'NOT_HEALTHY'):
                profile.selected_policy_dns(selected, states())

    def test_selected_running_consumer_and_absent_other_consumer_pass(self):
        for ownership, unit in (('bridge-managed', profile.POLICY_UNITS[0]),
                                ('external-policy', profile.POLICY_UNITS[1])):
            selected = dict(NATIVE, dnsOwnership=ownership, policyDnsUnits=[unit])
            observed = states()
            observed[unit] = dict(ABSENT, LoadState='loaded', ActiveState='active',
                                  MainPID='123', UnitFileState='enabled')
            with self.subTest(ownership=ownership):
                self.assertTrue(profile.selected_policy_dns(selected, observed))

    def test_selected_active_but_unloaded_or_zero_pid_fails(self):
        selected = dict(NATIVE, dnsOwnership='bridge-managed', policyDnsUnits=[profile.POLICY_UNITS[0]])
        for load, pid in (('not-found', '123'), ('masked', '123'), ('error', '123'), ('loaded', '0'), ('loaded', '²')):
            observed = states()
            observed[profile.POLICY_UNITS[0]] = dict(ABSENT, LoadState=load, ActiveState='active', MainPID=pid)
            with self.subTest(load=load, pid=pid), self.assertRaisesRegex(RuntimeError, 'NOT_HEALTHY'):
                profile.selected_policy_dns(selected, observed)

    def test_legacy_no_layout_does_not_adopt_failed_consumer(self):
        with self.assertRaisesRegex(RuntimeError, 'NOT_HEALTHY'):
            profile.selected_policy_dns(None, states(dict(ABSENT, LoadState='loaded',
                                                         UnitFileState='disabled', ActiveState='failed')))
        self.assertFalse(profile.selected_policy_dns(None, states()))

    def test_input_observations_are_not_rewritten(self):
        value = states(); before = copy.deepcopy(value)
        profile.selected_policy_dns(NATIVE, value)
        self.assertEqual(value, before)

    def test_missing_or_malformed_whole_state_is_rejected(self):
        for value in ({}, [], None, {profile.POLICY_UNITS[0]: ABSENT, profile.POLICY_UNITS[1]: None}):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, 'STATE_UNKNOWN'):
                profile.selected_policy_dns(NATIVE, value)

    def test_query_failure_and_timeout_are_not_absence(self):
        for error in (subprocess.CalledProcessError(1, ['systemctl']),
                      subprocess.TimeoutExpired(['systemctl'], 5), PermissionError('no bus')):
            with self.subTest(error=type(error).__name__), \
                 patch.object(profile.subprocess, 'run', side_effect=error), \
                 self.assertRaises(type(error)):
                profile.show(profile.POLICY_UNITS[0])

    def test_query_rejects_arbitrary_unit_before_subprocess(self):
        with patch.object(profile.subprocess, 'run') as run, self.assertRaisesRegex(RuntimeError, 'UNIT_REJECTED'):
            profile.show('unrelated.service')
        run.assert_not_called()

    def test_incomplete_duplicate_or_malformed_stdout_rejected(self):
        for text in ('', 'LoadState=not-found\n', raw(ABSENT) + 'LoadState=loaded\n',
                     raw(ABSENT) + 'warning\n', raw(ABSENT) + 'Other=unknown\n'):
            with self.subTest(text=text), \
                 patch.object(profile.subprocess, 'run', return_value=types.SimpleNamespace(stdout=text)), \
                 self.assertRaisesRegex(RuntimeError, 'STATE_UNKNOWN'):
                profile.show(profile.POLICY_UNITS[0])

    def test_native_preflight_rejects_missing_unit_contradiction_before_start(self):
        value = dict(ABSENT, UnitFileState='enabled')
        with patch.object(native, 'observe', return_value=value), \
             patch.object(native, 'ctl') as control, \
             self.assertRaisesRegex(RuntimeError, 'UNDECLARED'):
            native.verify_retired()
        control.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
