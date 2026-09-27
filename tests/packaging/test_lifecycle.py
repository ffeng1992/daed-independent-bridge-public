import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from types import SimpleNamespace
from scripts import release_lifecycle as lifecycle
from scripts.release_prepare import verify_archive

ROOT=Path(__file__).resolve().parents[2]

class LifecycleTests(unittest.TestCase):
    def test_entrypoints_work_outside_checkout(self):
        for name in ('install','upgrade','uninstall','health-check'):
            with self.subTest(name=name):
                r=subprocess.run(['sh',str(ROOT/(name+'.sh')),'--help'],cwd='/tmp',capture_output=True)
                self.assertEqual(r.returncode,0,r.stderr.decode())

    def test_purge_needs_confirmation_before_service_changes(self):
        with patch.object(lifecycle,'stop') as stop,patch.object(lifecycle,'purge') as purge:
            with self.assertRaisesRegex(RuntimeError,'EXPLICIT_CONFIRMATION'):
                lifecycle.execute('uninstall',SimpleNamespace(purge=True,confirm_purge=None))
            stop.assert_not_called();purge.assert_not_called()

    def test_missing_configuration_stops_before_service_or_download(self):
        with patch.object(Path,'exists',return_value=True),patch.object(lifecycle,'MANIFEST',Path('/nonexistent-manifest')),patch.object(Path,'read_text',return_value='{"files":{}}'),patch.object(lifecycle,'config_check',side_effect=RuntimeError('INITIAL_CONFIGURATION_REQUIRED')),patch.object(lifecycle,'stop') as stop,patch.object(lifecycle,'ready_payload') as prepare:
            with self.assertRaisesRegex(RuntimeError,'INITIAL_CONFIGURATION'):
                lifecycle.execute('install',SimpleNamespace())
            stop.assert_not_called();prepare.assert_not_called()

    def test_repeat_install_is_no_restart(self):
        files={'/opt/bridge/example':(b'code',0o644)}
        record={'files':{'/opt/bridge/example':{'sha256':hashlib.sha256(b'code').hexdigest(),'mode':0o644}}}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'manifest';p.write_text(json.dumps(record));(Path(d)/'release.json').write_text('{}')
            with patch.object(lifecycle,'MANIFEST',p),patch.object(lifecycle,'CFG',Path(d)),patch.object(lifecycle,'packages'),patch.object(lifecycle,'config_check'),patch.object(lifecycle,'ready_payload',return_value=files),patch('scripts.m4_install.verify_installed'),patch.object(lifecycle,'health') as health,patch.object(lifecycle,'stop') as stop,patch.object(lifecycle,'start') as start:
                lifecycle.execute('install',SimpleNamespace())
                health.assert_called_once();stop.assert_not_called();start.assert_not_called()

    def test_repeat_different_install_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'manifest';p.write_text(json.dumps({'files':{}}));(Path(d)/'release.json').write_text('{}')
            with patch.object(lifecycle,'MANIFEST',p),patch.object(lifecycle,'CFG',Path(d)),patch.object(lifecycle,'packages'),patch.object(lifecycle,'config_check'),patch.object(lifecycle,'ready_payload',return_value={'x':(b'x',0o644)}),patch('scripts.m4_install.verify_installed'),patch.object(lifecycle,'stop') as stop:
                with self.assertRaisesRegex(RuntimeError,'USE_UPGRADE'):lifecycle.execute('install',SimpleNamespace())
                stop.assert_not_called()

    def test_health_failure_is_not_swallowed(self):
        with patch.object(lifecycle,'health',side_effect=RuntimeError('DNS_QUERY_FAILED')):
            with self.assertRaisesRegex(RuntimeError,'DNS_QUERY_FAILED'):lifecycle.execute('health-check',SimpleNamespace())

    def test_purge_rejects_link_and_keeps_shared_dns(self):
        self.assertNotIn(Path('/etc/dae-dns-repair'),lifecycle.DATA)
        self.assertNotIn(Path('/var/lib/dae-ingress-sync'),lifecycle.DATA)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'keep').mkdir();(p/'link').symlink_to(p/'keep')
            with patch.object(lifecycle,'DATA',(p/'link',)):
                with self.assertRaisesRegex(RuntimeError,'SYMLINK'):lifecycle.purge()
            self.assertTrue((p/'keep').exists())

    def test_fresh_socket_has_no_mainpid(self):
        lifecycle.inactive_unit('bridge-helper.socket', 'ActiveState=inactive\n')
        lifecycle.inactive_unit('dae.service', 'ActiveState=inactive\nMainPID=0\n')
        for name, output in [('bridge-helper.socket', 'ActiveState=active'),
                             ('dae.service', 'ActiveState=inactive'),
                             ('dae.service', 'ActiveState=inactive\nMainPID=12')]:
            with self.assertRaisesRegex(RuntimeError, 'UNMANAGED_ACTIVE_SERVICE'):
                lifecycle.inactive_unit(name, output)

    def test_stop_closes_timers_before_oneshots_and_core(self):
        def ctl(*args):
            if args[0]=='show':return SimpleNamespace(stdout=b'ActiveState=failed\nMainPID=0\n')
            return SimpleNamespace(stdout=b'')
        with patch.object(lifecycle,'ctl',side_effect=ctl) as calls:
            lifecycle.stop()
            self.assertEqual(calls.call_args_list[0].args,('stop',*lifecycle.TIMERS))
            self.assertEqual(sum(c.args[0]=='reset-failed' for c in calls.call_args_list),sum(n.endswith('.service') for n in lifecycle.STOP))
            self.assertIn('dae.service',calls.call_args_list[2].args)
        with patch.object(lifecycle,'ctl',return_value=SimpleNamespace(stdout=b'ActiveState=active\nMainPID=99\n')):
            with self.assertRaisesRegex(RuntimeError,'SERVICE_STOP_FAILED'):lifecycle.stop()

    def test_locked_archive_and_members(self):
        f=io.BytesIO()
        with zipfile.ZipFile(f,'w') as z:z.writestr('dae-linux-x86_64',b'binary')
        raw=f.getvalue();pin={'sha256':hashlib.sha256(raw).hexdigest(),'archive_members':[{'path':'dae-linux-x86_64','size':6,'sha256':hashlib.sha256(b'binary').hexdigest()}]}
        self.assertEqual(verify_archive(raw,pin),{'dae-linux-x86_64':b'binary'})
        with self.assertRaisesRegex(RuntimeError,'ARCHIVE_HASH'):verify_archive(raw+b'x',pin)
        pin['archive_members'][0]['size']=7
        with self.assertRaisesRegex(RuntimeError,'MEMBER_HASH'):verify_archive(raw,pin)
