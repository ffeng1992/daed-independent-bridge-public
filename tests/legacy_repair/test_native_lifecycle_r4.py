"""Native lifecycle algorithms with explicit service substitutes, not systemd."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock,patch
from scripts import release_native_lifecycle as native
from bridge_m4 import maintenance_state as maintenance


class NativeStateTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.manifest=self.root/'install.json'
        self.before={n:{'LoadState':'loaded','ActiveState':'active','UnitFileState':'enabled','MainPID':'1','ControlPID':'0'} for n in native.OWNED}
        # Periodic jobs are not persistent active services (Type=oneshot).
        for name in native.PERIODIC:
            self.before[name].update(ActiveState='inactive',UnitFileState='static',MainPID='0')
        self.quiet={'LoadState':'loaded','ActiveState':'inactive','UnitFileState':'disabled','MainPID':'0','ControlPID':'0'}
    def test_retired_enabled_rejected_without_control(self):
        with patch.object(native,'observe',return_value=dict(self.quiet,UnitFileState='enabled')),patch.object(native,'ctl') as ctl:
            with self.assertRaisesRegex(RuntimeError,'BOOT_ENABLED'):native.verify_retired()
        ctl.assert_not_called()
    def test_retired_running_rejected(self):
        with patch.object(native,'observe',return_value=dict(self.quiet,ActiveState='active',MainPID='1')):
            with self.assertRaises(RuntimeError):native.verify_retired()
    def test_retired_quiet_disabled_accepted_without_control(self):
        with patch.object(native,'observe',return_value=self.quiet),patch.object(native,'ctl') as ctl:native.verify_retired()
        ctl.assert_not_called()
    def test_restore_first_error_does_not_skip_later_services(self):
        calls=[]
        def ctl(*args):
            calls.append(args)
            if args==('start',native.CORE[0]):raise OSError('secret')
        with patch.object(native,'ctl',side_effect=ctl),patch.object(native,'observe',side_effect=lambda n:self.before[n]):
            errors=native.restore_units(self.before)
        self.assertTrue(errors)
        self.assertEqual([x[1] for x in calls if x[0]=='start'],list((*native.CORE,*(n for n in native.ONESHOTS if n not in native.PERIODIC),*native.TIMERS)))
        self.assertNotIn('secret',str(errors))
    def test_restore_inactive_is_not_started(self):
        before={n:dict(self.quiet) for n in native.OWNED}
        with patch.object(native,'ctl') as ctl,patch.object(native,'observe',return_value=self.quiet):self.assertEqual(native.restore_units(before),[])
        self.assertFalse(any(c.args[0]=='start' for c in ctl.call_args_list))
    def test_stop_errors_are_reobserved(self):
        with patch.object(native,'ctl',side_effect=OSError),patch.object(native,'observe',return_value=self.quiet):
            warnings=native.stop_owned()
        self.assertEqual(len(warnings),len(native.OWNED))
    def test_stop_live_process_never_passes(self):
        with patch.object(native,'ctl'),patch.object(native,'observe',return_value=dict(self.quiet,MainPID='99')):
            with self.assertRaisesRegex(RuntimeError,'NOT_CONFIRMED'):native.stop_owned()
    def test_stop_never_targets_retired_dns(self):
        with patch.object(native,'ctl') as ctl,patch.object(native,'observe',return_value=self.quiet):native.stop_owned()
        self.assertFalse(any(n in native.RETIRED for c in ctl.call_args_list for n in c.args))
    def test_recovery_unrelated_transaction_is_rejected(self):
        tx=Mock();tx.load.return_value={'generation':'new','phase':'COMMITTED','context':{'kind':'other'}}
        with patch.object(native,'stop_owned',return_value=[]),patch.object(native,'observe',return_value=self.quiet),patch.object(native,'ctl'),patch.object(native,'restore_units') as start:
            result=native.recover(self.before,'old',tx,manifest_before={},install=Mock(),attempt_id='a'*32)
        self.assertFalse(result['complete']);self.assertFalse(result['filesRestored']);tx.restore.assert_not_called();start.assert_not_called()
    def test_recovery_broken_backup_never_starts_services(self):
        tx=Mock();tx.load.return_value={'generation':'new','phase':'COMMITTED','context':{'kind':'native-lifecycle','attemptId':'a'*32}}
        tx.restore.side_effect=RuntimeError('bad backup')
        with patch.object(native,'stop_owned',return_value=[]),patch.object(native,'observe',return_value=self.quiet),patch.object(native,'ctl'),patch.object(native,'restore_units') as start:
            result=native.recover(self.before,'old',tx,manifest_before={},install=Mock(),attempt_id='a'*32)
        self.assertFalse(result['filesRestored']);start.assert_not_called()
    def test_recovery_manifest_identity_rechecked_before_start(self):
        tx=Mock();tx.load.side_effect=[{'generation':'new','phase':'COMMITTED','context':{'kind':'native-lifecycle','attemptId':'a'*32}},{'phase':'RESTORED'}]
        self.manifest.write_text('{"files":{}}');before={'files':{}}
        self.before['dae.service']['ActiveState']='inactive'
        with patch.object(native,'MANIFEST',self.manifest),patch.object(native,'stop_owned',return_value=[]),patch.object(native,'observe',return_value=self.quiet),patch.object(native,'ctl'),patch.object(native,'restore_units',return_value=[]) as restart:
            installer=Mock();result=native.recover(self.before,'old',tx,manifest_before=before,install=installer,attempt_id='a'*32)
        self.assertTrue(result['complete']);installer.verify_installed.assert_called_once_with(before);restart.assert_called_once()
    def test_native_start_omits_all_policy_services_and_sync_timers(self):
        module=types.ModuleType('scripts.release_lifecycle');module.wait_for_management=Mock();module.wait_for_dataplane=Mock()
        with patch.dict('sys.modules',{'scripts.release_lifecycle':module}),patch.object(native,'ctl') as ctl:native.start_native()
        self.assertFalse(any(n in native.RETIRED for c in ctl.call_args_list for n in c.args))
        module.wait_for_dataplane.assert_called_once()
    def recovery_readiness(self, failure=None):
        tx=Mock();tx.load.return_value={'generation':'old'}
        self.manifest.write_text('{}')
        order=[]
        module=types.ModuleType('scripts.release_lifecycle')
        module.wait_for_management=Mock(side_effect=lambda:order.append('management'))
        def ready():
            order.append('dataplane')
            if failure:raise RuntimeError(failure)
        module.wait_for_dataplane=Mock(side_effect=ready)
        health=types.ModuleType('scripts.release_health');health.check=Mock(side_effect=lambda **kw:order.append('health'))
        with patch.dict('sys.modules',{'scripts.release_lifecycle':module,'scripts.release_health':health}),patch.object(native,'MANIFEST',self.manifest),patch.object(native,'stop_owned',return_value=[]),patch.object(native,'observe',return_value=self.quiet),patch.object(native,'ctl'),patch.object(native,'restore_units',return_value=[]):
            result=native.recover(self.before,'old',tx,manifest_before={},install=Mock(),attempt_id='a'*32)
        return result,order
    def test_restore_waits_for_readiness_before_full_health(self):
        result,order=self.recovery_readiness()
        self.assertTrue(result['complete']);self.assertEqual(order,['management','dataplane','health'])
    def test_restore_readiness_timeout_fails_closed(self):
        result,order=self.recovery_readiness('DATAPLANE_STARTUP_TIMEOUT')
        self.assertFalse(result['complete']);self.assertEqual(order,['management','dataplane'])
        self.assertEqual(result['errors'][0]['code'],'DATAPLANE_STARTUP_TIMEOUT')
    def test_setup_does_not_start_dataplane_or_geodata(self):
        module=types.ModuleType('scripts.release_lifecycle');module.wait_for_management=Mock();module.wait_for_dataplane=Mock()
        with patch.dict('sys.modules',{'scripts.release_lifecycle':module}),patch.object(native,'ctl') as ctl:native.start_native(setup=True)
        for c in ctl.call_args_list:self.assertNotIn('dae.service',c.args);self.assertNotIn('bridge-geodata-update.timer',c.args)
        module.wait_for_dataplane.assert_not_called()
    def test_purge_refused_before_loading_installer(self):
        with patch.object(native,'ctl') as ctl,self.assertRaisesRegex(RuntimeError,'PURGE'):
            native.execute('uninstall',types.SimpleNamespace(purge=True))
        ctl.assert_not_called()
    def test_unknown_observation_rejected(self):
        with patch.object(native,'ctl',return_value=types.SimpleNamespace(stdout='LoadState=error\nActiveState=inactive\n')):
            with self.assertRaisesRegex(RuntimeError,'UNKNOWN'):native.observe(native.CORE[0])
    def test_missing_pid_is_not_quiet(self):
        self.assertFalse(native.quiet('dae.service',{'ActiveState':'inactive'}))
    def test_maintenance_guard_blocks_incomplete_native_attempt(self):
        path=self.root/'native-lifecycle.json';path.write_text('{}')
        read=Mock(return_value={'phase':'STARTING'})
        with self.assertRaisesRegex(RuntimeError,'IN_PROGRESS'):maintenance.install_guard(self.root,read=read)
    def test_maintenance_guard_accepts_terminal_and_rechecks(self):
        (self.root/'native-lifecycle.json').write_text('{}');read=Mock(return_value={'phase':'ACCEPTED'})
        maintenance.install_guard(self.root,read=read);self.assertEqual(read.call_count,2)
    def test_maintenance_guard_rejects_change(self):
        (self.root/'transaction.json').write_text('{}');read=Mock(side_effect=[{'phase':'COMMITTED'},{'phase':'APPLYING'}])
        with self.assertRaisesRegex(RuntimeError,'CHANGED'):maintenance.install_guard(self.root,read=read)

if __name__=='__main__':unittest.main()
