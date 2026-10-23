"""R3 regression of independent review counterexamples; no real systemd writes."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from bridge_m4 import maintenance_state as primary
from scripts import release_management_plan as planner
from integration.ui_matrix import evidence_scope as scope


class PrimaryGuardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.authority = self.root / 'authority.json'
        self.state = self.root / 'state'; self.state.mkdir()
        self.units = {name: {'LoadState': 'loaded', 'ActiveState': 'inactive',
                    'MainPID': '0', 'ControlPID': '0', 'UnitFileState': 'disabled',
                    'NextElapseUSecRealtime': '0', 'NextElapseUSecMonotonic': '0'}
                    for name in primary.PROTECTION_UNITS}
        self.show = Mock(side_effect=lambda name: copy.deepcopy(self.units[name]))
        self.read = Mock(side_effect=lambda p: json.loads(Path(p).read_text()))
    def guard(self):
        return primary.primary_guard(self.state, self.authority, read=self.read, show=self.show)
    def test_empty_state_checks_all_protection_units(self):
        self.guard()
        self.assertEqual([c.args[0] for c in self.show.call_args_list], list(primary.PROTECTION_UNITS)*2)
        self.read.assert_not_called()
    def test_empty_state_with_active_timer_is_blocked(self):
        self.units['primary-rollback-phase1.timer']['ActiveState'] = 'active'
        with self.assertRaises(RuntimeError): self.guard()
        self.assertEqual(self.show.call_count, 4)
    def test_empty_state_with_enabled_timer_is_blocked(self):
        self.units['primary-rollback-phase2.timer']['UnitFileState'] = 'enabled'
        with self.assertRaises(RuntimeError): self.guard()
    def test_empty_state_with_pending_deadline_is_blocked(self):
        self.units['primary-rollback-phase2.timer']['NextElapseUSecMonotonic'] = '2000'
        with self.assertRaises(RuntimeError): self.guard()
    def test_empty_state_with_active_service_is_blocked(self):
        self.units['primary-rollback-phase1.service']['ActiveState'] = 'activating'
        with self.assertRaises(RuntimeError): self.guard()
    def test_empty_state_with_mainpid_is_blocked(self):
        self.units['primary-rollback-phase1.service']['MainPID'] = '42'
        with self.assertRaises(RuntimeError): self.guard()
    def test_empty_state_with_controlpid_is_blocked(self):
        self.units['primary-rollback-phase1.service']['ControlPID'] = '42'
        with self.assertRaises(RuntimeError): self.guard()
    def test_missing_loadstate_is_unknown(self):
        del self.units['primary-rollback-phase1.service']['LoadState']
        with self.assertRaises(RuntimeError): self.guard()
    def test_missing_loaded_service_pid_is_unknown(self):
        del self.units['primary-rollback-phase1.service']['MainPID']
        with self.assertRaises(RuntimeError): self.guard()
    def test_missing_loaded_timer_deadline_is_unknown(self):
        del self.units['primary-rollback-phase1.timer']['NextElapseUSecRealtime']
        with self.assertRaises(RuntimeError): self.guard()
    def test_query_failure_is_not_absence(self):
        self.show.side_effect = subprocess.CalledProcessError(1, ['systemctl'])
        with self.assertRaises(subprocess.CalledProcessError): self.guard()
    def test_genuinely_absent_units_and_no_attempt_pass(self):
        self.units = {n: {'LoadState':'not-found','ActiveState':'inactive'} for n in primary.PROTECTION_UNITS}
        self.guard()
    def test_contradictory_absent_active_unit_rejected(self):
        self.units = {n: {'LoadState':'not-found','ActiveState':'active'} for n in primary.PROTECTION_UNITS}
        with self.assertRaises(RuntimeError): self.guard()
    def test_orphan_authority_is_incomplete(self):
        self.authority.write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE'): self.guard()
    def test_broken_authority_symlink_is_not_absent(self):
        self.authority.symlink_to(self.root / 'missing')
        with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE'): self.guard()
    def test_new_marker_between_observations_is_blocked(self):
        count = [0]
        def show(name):
            count[0] += 1
            if count[0] == 5: (self.state/'rollback-required.json').write_text('{}')
            return copy.deepcopy(self.units[name])
        self.show.side_effect = show
        # This race is noticed on the final state recheck (R3 regression).
        with self.assertRaisesRegex(RuntimeError, 'STATE_CHANGED'): self.guard()
    def test_activation_on_second_probe_is_blocked(self):
        count = [0]
        def show(name):
            count[0] += 1
            u = copy.deepcopy(self.units[name])
            if count[0] == 8: u['ActiveState'] = 'active'
            return u
        self.show.side_effect = show
        with self.assertRaises(RuntimeError): self.guard()
    def test_unit_probe_is_read_only_and_requests_loadstate(self):
        with patch.object(primary.subprocess, 'run', return_value=Mock(returncode=0, stdout='LoadState=not-found\nActiveState=inactive\n')) as run:
            primary._unit('primary-rollback-phase1.timer')
        args = run.call_args.args[0]
        self.assertEqual(args[:2], ['/usr/bin/systemctl','show'])
        self.assertIn('LoadState', args[-1])


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.before = {n:{'ActiveState':'active'} for n in (*planner.MANAGEMENT,*planner.TIMERS)}
        self.quiet = {'LoadState':'loaded','ActiveState':'inactive','MainPID':'0','ControlPID':'0'}
    def test_first_service_failure_does_not_short_circuit_other_services_or_timers(self):
        calls = []
        def control(action,name):
            calls.append((action,name))
            if name == planner.MANAGEMENT[0]: raise RuntimeError('first failed')
        with patch.object(planner, 'control', side_effect=control), patch.object(planner, 'unit', return_value={'ActiveState':'active'}):
            with self.assertRaises(planner.RecoveryFailure) as caught: planner._restore_states(self.before)
        self.assertEqual(calls, [('start',n) for n in (*planner.MANAGEMENT,*planner.TIMERS)])
        self.assertEqual(len(caught.exception.report['errors']), 1)
    def test_multiple_failures_are_all_recorded(self):
        with patch.object(planner, 'control', side_effect=OSError('secret command output')), patch.object(planner, 'unit', return_value={'ActiveState':'inactive'}):
            with self.assertRaises(planner.RecoveryFailure) as caught: planner._restore_states(self.before)
        self.assertEqual(len(caught.exception.report['errors']), 2*len(self.before))
        self.assertNotIn('secret', json.dumps(caught.exception.report))
    def test_inactive_units_are_not_started_and_no_enable(self):
        self.before[planner.MANAGEMENT[0]]['ActiveState'] = 'inactive'
        with patch.object(planner, 'control') as control, patch.object(planner, 'unit', return_value={'ActiveState':'active'}):
            planner._restore_states(self.before)
        self.assertNotIn(('start',planner.MANAGEMENT[0]), [c.args for c in control.call_args_list])
        self.assertTrue(all(c.args[0]=='start' for c in control.call_args_list))
    def test_successful_command_but_inactive_readback_is_failure(self):
        with patch.object(planner, 'control'), patch.object(planner, 'unit', return_value={'ActiveState':'inactive'}):
            with self.assertRaisesRegex(planner.RecoveryFailure, 'INCOMPLETE'): planner._restore_states(self.before)
    def test_stop_command_failure_still_restores_files_when_stopped_is_proved(self):
        tx = Mock()
        with patch.object(planner, 'control', side_effect=RuntimeError('stop failed')), \
             patch.object(planner, 'unit', return_value=self.quiet), \
             patch.object(planner, '_restore_states') as restore, \
             patch.object(planner, '_same_dataplane'):
            r = planner._recover_failed_apply(self.before,{},tx,begun=True,stopped=True)
        tx.restore.assert_called_once(); restore.assert_called_once_with(self.before)
        self.assertTrue(r['complete']); self.assertEqual(len(r['commandWarnings']),len(self.before))
    def test_live_process_prevents_unsafe_file_restore_and_restart(self):
        tx = Mock()
        with patch.object(planner, 'control'), patch.object(planner, 'unit', return_value={**self.quiet,'MainPID':'99'}), \
             patch.object(planner, '_restore_states') as restore, patch.object(planner, '_same_dataplane') as same:
            r = planner._recover_failed_apply(self.before,{},tx,begun=True,stopped=True)
        tx.restore.assert_not_called(); restore.assert_not_called(); same.assert_called_once()
        self.assertFalse(r['complete']); self.assertFalse(r['filesRestored'])
    def test_live_control_process_prevents_restore(self):
        tx=Mock()
        with patch.object(planner,'control'), patch.object(planner,'unit',return_value={**self.quiet,'ControlPID':'4'}), \
             patch.object(planner,'_same_dataplane'):
            r=planner._recover_failed_apply(self.before,{},tx,begun=True,stopped=True)
        tx.restore.assert_not_called();self.assertFalse(r['complete'])
    def test_file_restore_failure_keeps_services_stopped(self):
        tx=Mock();tx.restore.side_effect=OSError('disk error')
        with patch.object(planner,'control'), patch.object(planner,'unit',return_value=self.quiet), \
             patch.object(planner,'_restore_states') as restore,patch.object(planner,'_same_dataplane'):
            r=planner._recover_failed_apply(self.before,{},tx,begun=True,stopped=True)
        restore.assert_not_called();self.assertFalse(r['complete'])
        self.assertIn('restore-files',[x['stage'] for x in r['errors']])
    def test_restore_service_failure_does_not_skip_other_recovery_checks(self):
        tx=Mock(); checked=[]
        with patch.object(planner,'control'),patch.object(planner,'unit',return_value=self.quiet), \
             patch.object(planner,'_restore_states',side_effect=planner.RecoveryFailure('x',{'errors':[{'stage':'start'}]})), \
             patch.object(planner,'_same_dataplane') as same:
            r=planner._recover_failed_apply(self.before,{},tx,begun=True,stopped=True,
                                           checks=(('db',lambda:checked.append('db')),('source',lambda:checked.append('source'))))
        same.assert_called_once();self.assertEqual(checked,['db','source']);self.assertFalse(r['complete'])
    def test_readback_failure_does_not_skip_later_readbacks(self):
        checked=[]
        def bad():checked.append('first');raise RuntimeError('bad')
        with patch.object(planner,'_restore_states'),patch.object(planner,'_same_dataplane',side_effect=RuntimeError('dae changed')):
            r=planner._recover_failed_apply(self.before,{},Mock(),begun=False,stopped=True,
                                           checks=(('first',bad),('last',lambda:checked.append('last'))))
        self.assertEqual(checked,['first','last']);self.assertEqual(len(r['errors']),2)
    def test_no_file_transaction_restores_only_prior_services(self):
        tx=Mock()
        with patch.object(planner,'_restore_states') as restore,patch.object(planner,'_same_dataplane'),patch.object(planner,'control') as ctl:
            r=planner._recover_failed_apply(self.before,{},tx,begun=False,stopped=True)
        tx.restore.assert_not_called();ctl.assert_not_called();restore.assert_called_once();self.assertTrue(r['complete'])
    def test_unknown_stop_readback_is_incomplete_not_success(self):
        with patch.object(planner,'control'),patch.object(planner,'unit',return_value={}),patch.object(planner,'_same_dataplane'):
            r=planner._recover_failed_apply(self.before,{},Mock(),begun=True,stopped=True)
        self.assertFalse(r['complete']);self.assertFalse(r['serviceRestoreAttempted'])
    def test_cleanup_is_bounded_to_known_management_and_timers(self):
        with patch.object(planner,'control') as control,patch.object(planner,'unit',return_value=self.quiet):
            planner._quiesce_for_restore(self.before)
        names=[c.args[1] for c in control.call_args_list]
        self.assertEqual(set(names),set(self.before));self.assertNotIn('dae.service',names)
        self.assertNotIn('daed-api.service',names)


class SourceScopeTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name).resolve();self.source=self.root/'source';self.source.mkdir()
        self.evidence=self.root/'evidence';self.evidence.mkdir()
        (self.source/'upstream.lock.json').write_text('{}')
    def put(self,name,data='before\n'):
        p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data);return p
    def test_deployment_unit_changes_fingerprint(self):
        p=self.put('deployment/release/units/a.service');before=scope.fingerprint(self.source)
        p.write_text('after\n');self.assertNotEqual(before,scope.fingerprint(self.source))
    def test_root_install_entry_changes_fingerprint(self):
        p=self.put('install.sh');before=scope.fingerprint(self.source)
        p.write_text('after\n');self.assertNotEqual(before,scope.fingerprint(self.source))
    def test_all_root_shell_entries_are_covered(self):
        for name in ('install.sh','upgrade.sh','uninstall.sh','health-check.sh','new-entry.sh'):
            with self.subTest(name=name):
                p=self.put(name);before=scope.fingerprint(self.source);p.write_text('changed\n')
                self.assertNotEqual(before,scope.fingerprint(self.source))
    def test_deployment_mode_changes_fingerprint(self):
        p=self.put('deployment/entry.sh');p.chmod(0o644);before=scope.fingerprint(self.source)
        p.chmod(0o755);self.assertNotEqual(before,scope.fingerprint(self.source))
    def test_dependency_lock_changes_fingerprint(self):
        p=self.put('requirements-linux.lock');before=scope.fingerprint(self.source)
        p.write_text('after\n');self.assertNotEqual(before,scope.fingerprint(self.source))
    def test_all_declared_source_prefixes_covered(self):
        for name in scope.PREFIXES:
            with self.subTest(name=name):
                p=self.put(name+'/test.py');before=scope.fingerprint(self.source);p.write_text('new\n')
                self.assertNotEqual(before,scope.fingerprint(self.source))
    def test_queries_stay_covered(self):
        p=self.put('contracts/queries/nodes.graphql');before=scope.fingerprint(self.source)
        p.write_text('query{changed}');self.assertNotEqual(before,scope.fingerprint(self.source))
    def test_source_file_deletion_changes_fingerprint(self):
        p=self.put('deployment/x.service');before=scope.fingerprint(self.source)
        p.unlink();self.assertNotEqual(before,scope.fingerprint(self.source))
    def test_outputs_do_not_invalidate_source(self):
        before=scope.fingerprint(self.source)
        for name in ('out/run.log','.git/index','official/dae.zip','bridge_m4/__pycache__/x.pyc'):
            self.put(name)
        self.assertEqual(before,scope.fingerprint(self.source))
    def test_deployment_root_symlink_is_rejected(self):
        outside=self.root/'outside';outside.mkdir();(self.source/'deployment').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,'SOURCE_LINK'):scope.fingerprint(self.source)
    def test_source_nested_symlink_is_rejected(self):
        folder=self.source/'deployment';folder.mkdir();(folder/'x').symlink_to(self.source/'upstream.lock.json')
        with self.assertRaisesRegex(RuntimeError,'SOURCE_LINK'):scope.fingerprint(self.source)
    def test_root_shell_symlink_is_rejected(self):
        (self.source/'install.sh').symlink_to('upstream.lock.json')
        with self.assertRaises(RuntimeError):scope.fingerprint(self.source)
    def test_change_only_deployment_refuses_resume(self):
        p=self.put('deployment/test.service');scope.start_run(self.source,self.evidence,boot='synthetic')
        p.write_text('after\n')
        with self.assertRaisesRegex(RuntimeError,'CONTEXT_CHANGED'):scope.current(self.source,self.evidence,boot='synthetic')
    def test_old_fingerprint_version_is_not_reused(self):
        scope.start_run(self.source,self.evidence,boot='synthetic')
        p=self.evidence/'matrix-run.json';value=json.loads(p.read_text());value['fingerprintVersion']=1;p.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError,'RUN_SCHEMA'):scope.current(self.source,self.evidence,boot='synthetic')
    def test_offline_report_is_bound_to_selected_source_not_host_boot(self):
        v=scope.start_run(self.source,self.evidence,boot='different-host-boot')
        folder=self.evidence/'runs'/v['runId']
        self.assertEqual(scope.report_scope(folder,source=self.source),v)
    def test_report_rejects_old_source_identity(self):
        v=scope.start_run(self.source,self.evidence,boot='synthetic');self.put('deployment/changed.service')
        with self.assertRaisesRegex(RuntimeError,'REPORT_SOURCE_CHANGED'):
            scope.report_scope(self.evidence/'runs'/v['runId'],source=self.source)
    def test_report_rejects_unscoped_evidence_directory(self):
        with self.assertRaises((OSError,RuntimeError)):scope.report_scope(self.evidence,source=self.source)
    def test_ledger_path_escape_is_rejected(self):
        for name in ('../old.json','/tmp/old.json','dir/../../old.json','x\\y'):
            with self.subTest(name=name),self.assertRaises(RuntimeError):scope.evidence_path(self.evidence,name)
    def test_ledger_symlink_is_rejected(self):
        (self.evidence/'link').symlink_to(self.source/'upstream.lock.json')
        with self.assertRaises(RuntimeError):scope.evidence_path(self.evidence,'link')
    def test_ledger_regular_relative_path_is_accepted(self):
        p=scope.evidence_path(self.evidence,'new.json');self.assertEqual(p,self.evidence/'new.json')


if __name__ == '__main__': unittest.main(verbosity=2)

class ProtectionQueryTests(unittest.TestCase):
    def query(self, code, output):
        with patch.object(primary.subprocess, 'run', return_value=types.SimpleNamespace(
                returncode=code, stdout=output)) as run:
            value=primary._unit(primary.PROTECTION_UNITS[0])
            self.assertIn('--all',run.call_args.args[0])
            self.assertFalse(run.call_args.kwargs['check'])
            return value
    def test_successful_show_preserves_property_response(self):
        self.assertEqual(self.query(0,'LoadState=loaded\nActiveState=inactive\nMainPID=0\n')['MainPID'],'0')
    def test_nonzero_explicit_absence_is_not_transport_failure(self):
        for rc in (1,4):
            self.assertEqual(self.query(rc,'LoadState=not-found\nActiveState=inactive\n')['LoadState'],'not-found')
    def test_nonzero_bus_error_cannot_mean_absent(self):
        for rc in (1,4):
            with self.assertRaisesRegex(RuntimeError,'QUERY_FAILED'):self.query(rc,'')
    def test_nonzero_loaded_unit_cannot_mean_absent(self):
        with self.assertRaisesRegex(RuntimeError,'QUERY_FAILED'):
            self.query(1,'LoadState=loaded\nActiveState=inactive\n')
    def test_nonzero_absent_but_active_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'QUERY_FAILED'):
            self.query(4,'LoadState=not-found\nActiveState=active\n')
    def test_unrecognized_query_failure_stays_closed(self):
        with self.assertRaisesRegex(RuntimeError,'QUERY_FAILED'):
            self.query(126,'LoadState=not-found\nActiveState=inactive\n')
