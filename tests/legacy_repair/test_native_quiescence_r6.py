"""Transition/trigger state machine tests. systemctl is a stateful test double.

These tests never call host systemctl and are NOT real systemd acceptance.
"""
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from scripts import release_native_lifecycle as n
from bridge_m4 import maintenance_state


def state(active='inactive', *, load='loaded', enabled='static', pid='0', control='0'):
    return {'LoadState': load, 'ActiveState': active, 'UnitFileState': enabled,
            'MainPID': pid, 'ControlPID': control}


def output(value):
    return SimpleNamespace(stdout=''.join(k+'='+str(v)+'\n' for k, v in value.items()))


class ObservationTests(unittest.TestCase):
    def test_strict_read_still_rejects_activating(self):
        for unit in (n.CORE[0], n.PERIODIC[0], n.RETIRED[0]):
            with self.subTest(unit=unit), patch.object(n, 'ctl', return_value=output(state('activating', pid='7'))):
                with self.assertRaisesRegex(RuntimeError, 'NATIVE_UNIT_TRANSITION'):
                    n.observe(unit)

    def test_transitional_periodic_read_is_not_a_health_pass(self):
        for active in ('activating', 'deactivating'):
            value = dict(state(active, pid='7'), Type='oneshot', RemainAfterExit='no')
            with self.subTest(state=active), patch.object(n, 'ctl', return_value=output(value)):
                seen = n.observe(n.PERIODIC[0], allow_transition=True)
                self.assertFalse(n.quiet(n.PERIODIC[0], seen))
                self.assertEqual(seen['ActiveState'], active)

    def test_allow_transition_never_applies_to_retired(self):
        with patch.object(n, 'ctl') as ctl:
            with self.assertRaisesRegex(RuntimeError, 'NOT_OWNED'):
                n.observe(n.RETIRED[0], allow_transition=True)
            ctl.assert_not_called()

    def test_changed_worker_type_is_not_silently_drained(self):
        for typ, remain in (('simple', 'no'), ('oneshot', 'yes'), ('', ''), ('oneshot', '')):
            with self.subTest(typ=typ,remain=remain), patch.object(n, 'ctl', return_value=output(
                    dict(state('activating', pid='7'), Type=typ, RemainAfterExit=remain))):
                with self.assertRaisesRegex(RuntimeError, 'PERIODIC_UNIT_IDENTITY'):
                    n.observe(n.PERIODIC[0], allow_transition=True)

    def test_uninstalled_periodic_unit_is_not_required_to_have_service_type(self):
        value = state(load='not-found',enabled='')
        with patch.object(n, 'ctl', return_value=output(value)):
            self.assertTrue(n.quiet(n.PERIODIC[0], n.observe(n.PERIODIC[0], allow_transition=True)))

    def test_unknown_states_and_missing_pids_still_fail_closed(self):
        for value in (dict(state(), LoadState='error'), dict(state(), ActiveState='refreshing'),
                      dict(state(), MainPID=''), dict(state(), ControlPID='garbage')):
            value.update(Type='oneshot', RemainAfterExit='no')
            with self.subTest(value=value), patch.object(n,'ctl',return_value=output(value)):
                with self.assertRaises(RuntimeError):n.observe(n.PERIODIC[0],allow_transition=True)

    def test_unknown_owned_name_never_reaches_systemctl(self):
        with patch.object(n,'ctl') as ctl:
            with self.assertRaisesRegex(RuntimeError,'NOT_OWNED'):n.observe('other.service',allow_transition=True)
            ctl.assert_not_called()

    def test_query_timeout_is_bounded_by_remaining_drain_budget(self):
        value=dict(state(),Type='oneshot',RemainAfterExit='no')
        with patch.object(n.time,'monotonic',return_value=5.0),patch.object(n,'ctl',return_value=output(value)) as ctl:
            n.observe(n.PERIODIC[0],allow_transition=True,deadline=5.25)
        self.assertEqual(ctl.call_args.kwargs['timeout'],0.25)

    def test_slow_query_cannot_report_late_quiet_state_as_in_budget(self):
        value=dict(state(),Type='oneshot',RemainAfterExit='no')
        with patch.object(n.time,'monotonic',side_effect=[5.0,5.5]),patch.object(n,'ctl',return_value=output(value)):
            with self.assertRaisesRegex(RuntimeError,'DRAIN_TIMEOUT'):
                n.observe(n.PERIODIC[0],allow_transition=True,deadline=5.25)


class DrainTests(unittest.TestCase):
    def setUp(self):
        self.states={unit:state() for unit in (*n.TIMERS,*n.PERIODIC)}
        self.now=0.0;self.sleeps=[]
    def read(self, unit, **_):return dict(self.states[unit])
    def sleep(self, seconds):self.sleeps.append(seconds);self.now+=seconds
    def environment(self):
        stack=ExitStack()
        stack.enter_context(patch.object(n,'observe',side_effect=self.read))
        stack.enter_context(patch.object(n.time,'monotonic',side_effect=lambda:self.now))
        stack.enter_context(patch.object(n.time,'sleep',side_effect=self.sleep))
        stack.enter_context(patch.object(n,'ctl',side_effect=AssertionError('no control during natural drain')))
        return stack
    def test_quiet_jobs_return_without_sleep_or_control(self):
        with self.environment():self.assertEqual(set(n.drain_periodic()),set(n.PERIODIC))
        self.assertEqual(self.sleeps,[])
    def test_running_job_finishes_naturally(self):
        unit=n.PERIODIC[1];self.states[unit]=state('activating',pid='7')
        def sleep(seconds):self.now+=seconds;self.states[unit]=state()
        self.sleep=sleep
        with self.environment():n.drain_periodic(timeout=0.3)
        self.assertGreater(self.now,0)
    def test_deadline_not_reset_for_persistently_running_job(self):
        self.states[n.PERIODIC[1]]=state('activating',pid='7')
        with self.environment(),self.assertRaisesRegex(RuntimeError,'PERIODIC_DRAIN_TIMEOUT'):
            n.drain_periodic(timeout=0.25)
        self.assertAlmostEqual(self.now,0.25)
        self.assertEqual(len(self.sleeps),3)
    def test_residual_control_pid_does_not_count_as_exit(self):
        self.states[n.PERIODIC[0]]=state(control='99')
        with self.environment(),self.assertRaisesRegex(RuntimeError,'DRAIN_TIMEOUT'):
            n.drain_periodic(timeout=0.1)
    def test_timer_reactivation_aborts_without_killing_worker(self):
        self.states[n.TIMERS[0]]=state('active')
        with self.environment(),self.assertRaisesRegex(RuntimeError,'TRIGGER_REACTIVATED'):
            n.drain_periodic()
    def test_second_read_detects_worker_reactivation(self):
        calls=[]
        def read(unit,**_):
            calls.append(unit)
            if unit==n.PERIODIC[1] and calls.count(unit)==2:return state('activating',pid='9')
            return dict(self.states[unit])
        self.read=read
        with self.environment():n.drain_periodic(timeout=0.5)
        self.assertEqual(len(self.sleeps),1)
    def test_unknown_read_is_not_retried_as_transient(self):
        with patch.object(n,'observe',side_effect=RuntimeError('unknown')) as read:
            with self.assertRaisesRegex(RuntimeError,'unknown'):n.drain_periodic()
        self.assertEqual(read.call_count,1)
    def test_invalid_timeout_rejected(self):
        for seconds in (True,0,-1,91,float('nan')):
            with self.subTest(seconds=seconds),self.assertRaisesRegex(RuntimeError,'TIMEOUT_RANGE'):
                n.drain_periodic(timeout=seconds)


class TriggerAndRestoreTests(unittest.TestCase):
    def setUp(self):
        self.states={unit:state() for unit in n.OWNED}
        self.calls=[]
    def read(self,unit,**_):return dict(self.states[unit])
    def ctl(self,*args):
        self.calls.append(args)
        action,name=args[0],args[-1]
        if name in self.states:
            if action=='stop':self.states[name].update(ActiveState='inactive',MainPID='0',ControlPID='0')
            elif action=='start':self.states[name].update(ActiveState='active',MainPID='11')
        return SimpleNamespace(stdout='')
    def test_stops_timers_and_socket_before_first_service(self):
        with patch.object(n,'observe',side_effect=self.read),patch.object(n,'ctl',side_effect=self.ctl):n.stop_owned()
        stops=[c[-1] for c in self.calls if c[0]=='stop']
        self.assertEqual(stops[:len(n.TRIGGERS)],list(n.TRIGGERS))
        self.assertLess(stops.index('bridge-helper.socket'),stops.index('bridge-helper.service'))
    def test_stop_command_can_stop_transition_but_never_certifies_it_as_quiet(self):
        self.states['dae.service']=state('deactivating',pid='9')
        with patch.object(n,'observe',side_effect=self.read),patch.object(n,'ctl',side_effect=self.ctl):n.stop_owned()
        self.assertIn(('stop','dae.service'),self.calls)
    def test_unconfirmed_trigger_stop_blocks_all_consumer_stops(self):
        self.states[n.TIMERS[0]]=state('active')
        def ctl(*args):
            self.calls.append(args)
            if args[-1]!=n.TIMERS[0]:self.states[args[-1]]=state()
        with patch.object(n,'observe',side_effect=self.read),patch.object(n,'ctl',side_effect=ctl):
            with self.assertRaisesRegex(RuntimeError,'TRIGGER_STOP_NOT_CONFIRMED'):n.stop_owned()
        self.assertTrue(all(c[-1] in n.TRIGGERS for c in self.calls))
    def test_error_after_actual_trigger_stop_is_retained_and_does_not_block_safe_stop(self):
        def ctl(*args):self.ctl(*args);raise OSError('private detail')
        with patch.object(n,'observe',side_effect=self.read),patch.object(n,'ctl',side_effect=ctl):warnings=n.stop_owned()
        self.assertTrue(warnings);self.assertNotIn('private detail',str(warnings))
    def test_restore_timers_continues_after_first_error(self):
        before={unit:state('active',enabled='enabled') for unit in n.TIMERS}
        for unit in n.TIMERS:self.states[unit]=state(enabled='enabled')
        def ctl(*args):
            if args[-1]==n.TIMERS[0]:self.calls.append(args);raise OSError('failure')
            return self.ctl(*args)
        with patch.object(n,'observe',side_effect=self.read),patch.object(n,'ctl',side_effect=ctl):errors=n.restore_timers(before)
        self.assertTrue(errors);self.assertIn(('start',n.TIMERS[1]),self.calls)
        self.assertFalse(any(c[0] in {'enable','disable'} for c in self.calls))
    def test_previously_inactive_timer_is_not_started(self):
        before={unit:state(enabled='disabled') for unit in n.TIMERS}
        self.states.update(copy.deepcopy(before))
        with patch.object(n,'observe',side_effect=self.read),patch.object(n,'ctl',side_effect=self.ctl):
            self.assertEqual(n.restore_timers(before),[])
        self.assertFalse(any(c[0]=='start' for c in self.calls))
    def test_timer_configuration_drift_is_not_overwritten(self):
        before={unit:state('active',enabled='enabled') for unit in n.TIMERS}
        with patch.object(n,'observe',side_effect=self.read),patch.object(n,'ctl',side_effect=self.ctl):errors=n.restore_timers(before)
        self.assertTrue(errors);self.assertEqual(self.calls,[])
    def test_old_active_periodic_snapshot_cannot_be_replayed(self):
        before=copy.deepcopy(self.states);before[n.PERIODIC[1]]=state('active',pid='9')
        with patch.object(n,'ctl') as ctl:errors=n.restore_units(before)
        self.assertTrue(errors);ctl.assert_not_called()
    def test_restart_timer_triggering_oneshot_does_not_break_restoration_readback(self):
        before=copy.deepcopy(self.states)
        for unit in n.TIMERS:before[unit]=state('active',enabled='enabled');self.states[unit]=state(enabled='enabled')
        def ctl(*args):
            self.ctl(*args)
            if args[0]=='start' and args[-1] in n.TIMERS:
                self.states[n.PERIODIC[1]]=state('activating',pid='42')
        def read(unit,**kwargs):
            value=self.read(unit,**kwargs)
            if value['ActiveState']=='activating' and not kwargs.get('allow_transition'):
                raise RuntimeError('NATIVE_UNIT_TRANSITION')
            return value
        with patch.object(n,'observe',side_effect=read),patch.object(n,'ctl',side_effect=ctl):
            self.assertEqual(n.restore_units(before),[])
        self.assertFalse(any(c[0]=='start' and c[-1] in n.PERIODIC for c in self.calls))


class PreflightJournalTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.path=self.root/'native-lifecycle.json'
        self.tx=Mock(ROOT=self.root);self.tx.load.return_value={'phase':'COMMITTED','generation':'old'}
        self.attempt={'schemaVersion':1,'attemptId':'a'*32,'phase':'QUIESCING','recoveryScope':'triggers-only',
                      'previousGeneration':'old','manifestBefore':None,
                      'beforeTimers':{unit:state('active',enabled='enabled') for unit in n.TIMERS}}
    def save(self,value):self.path.write_text(json.dumps(value));self.path.chmod(0o600)
    def trusted_fixture(self,path):
        # Schema tests begin after the separately tested root-authority reader.
        self.assertEqual(path,self.path)
        return json.loads(path.read_text())
    def test_quiescing_journal_can_resume_without_fabricated_full_snapshot(self):
        self.save(self.attempt)
        with patch.object(maintenance_state,'_read',side_effect=self.trusted_fixture) as read:
            self.assertEqual(n.read_attempt(self.tx),self.attempt)
        read.assert_called_once_with(self.path)
    def test_unknown_or_ambiguous_partial_journal_is_rejected(self):
        for changes in ({'recoveryScope':'other'},{'phase':'APPLYING'}, {'beforeTimers':{}},
                        {'beforeUnits':{}}):
            self.save(dict(self.attempt,**changes))
            with patch.object(maintenance_state,'_read',side_effect=self.trusted_fixture) as read:
                with self.assertRaisesRegex(RuntimeError,'LIFECYCLE_JOURNAL'):n.read_attempt(self.tx)
            read.assert_called_once_with(self.path)
    def test_changed_installer_journal_keeps_triggers_stopped(self):
        self.tx.load.return_value={'phase':'APPLYING','generation':'other'}
        with patch.object(n,'restore_timers') as restore:
            result=n.recover_trigger_preflight(self.attempt,self.tx,Mock())
        self.assertFalse(result['complete']);restore.assert_not_called();self.tx.restore.assert_not_called()
    def test_preflight_recovery_does_not_touch_core_or_restore_files(self):
        with patch.object(n,'MANIFEST',self.root/'absent'),patch.object(n,'restore_timers',return_value=[]) as timers, \
             patch.object(n,'stop_owned') as stop,patch.object(n,'restore_units') as core:
            result=n.recover_trigger_preflight(self.attempt,self.tx,Mock())
        self.assertTrue(result['complete']);timers.assert_called_once();stop.assert_not_called();core.assert_not_called();self.tx.restore.assert_not_called()
    def test_failed_timer_restore_remains_pending(self):
        with patch.object(n,'MANIFEST',self.root/'absent'),patch.object(n,'restore_timers',return_value=[{'unit':n.TIMERS[0]}]):
            result=n.recover_trigger_preflight(self.attempt,self.tx,Mock())
        self.assertFalse(result['complete'])


class JournalAuthorityTests(unittest.TestCase):
    """Exercise the real reader with synthetic kernel ownership, never chown/sudo."""
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name).resolve()/'native-lifecycle.json'
        self.path.write_text('{"schemaVersion":1}');self.path.chmod(0o600)
        self.fstat=os.fstat

    def metadata(self,*,directory_uid=0,directory_writable=False,file_uid=0):
        def observe(fd):
            value=self.fstat(fd)
            fields={name:getattr(value,name) for name in dir(value) if name.startswith('st_')}
            directory=stat.S_ISDIR(value.st_mode)
            fields['st_uid']=directory_uid if directory else file_uid
            if directory and directory_writable:fields['st_mode']|=0o020
            return SimpleNamespace(**fields)
        return observe

    def test_root_owned_private_journal_is_read(self):
        with patch.object(os,'fstat',side_effect=self.metadata()):
            self.assertEqual(maintenance_state._read(self.path),{'schemaVersion':1})

    def test_nonroot_parent_is_rejected_before_file_read(self):
        with patch.object(os,'fstat',side_effect=self.metadata(directory_uid=1001)), \
             patch.object(maintenance_state,'read_json') as read:
            with self.assertRaisesRegex(RuntimeError,'ROLLBACK_STATE_AUTHORITY'):
                maintenance_state._read(self.path)
        read.assert_not_called()

    def test_writable_parent_is_rejected_before_file_read(self):
        with patch.object(os,'fstat',side_effect=self.metadata(directory_writable=True)), \
             patch.object(maintenance_state,'read_json') as read:
            with self.assertRaisesRegex(RuntimeError,'ROLLBACK_STATE_AUTHORITY'):
                maintenance_state._read(self.path)
        read.assert_not_called()

    def test_nonroot_file_is_rejected(self):
        with patch.object(os,'fstat',side_effect=self.metadata(file_uid=1001)):
            with self.assertRaisesRegex(ValueError,'HISTORY_FILE_AUTHORITY'):
                maintenance_state._read(self.path)

    def test_wrong_file_mode_is_rejected(self):
        self.path.chmod(0o640)
        with patch.object(os,'fstat',side_effect=self.metadata()):
            with self.assertRaisesRegex(ValueError,'HISTORY_FILE_AUTHORITY'):
                maintenance_state._read(self.path)


if __name__=='__main__':unittest.main()
