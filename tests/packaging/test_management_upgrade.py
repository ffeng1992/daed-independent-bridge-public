"""Management-only packaging preserves data-plane/DNS ownership."""
import unittest
from unittest.mock import patch
from scripts import release_management_plan as planner
from scripts import management_payload

class ManagementUpgradePlanTests(unittest.TestCase):
    def test_dns_and_official_units_outside_write_scope(self):
        for name in ('/etc/systemd/system/dae.service','bridge-lan-dns.service','/opt/bridge-official/dae'):
            self.assertFalse(management_payload.eligible(name))
    def test_api_and_dae_not_stopped_by_management_plan(self):
        self.assertNotIn('daed-api.service',planner.MANAGEMENT)
        self.assertNotIn('dae.service',planner.MANAGEMENT)
        self.assertLess(planner.MANAGEMENT.index('bridge-graphql.service'),planner.MANAGEMENT.index('daed-web.service'))
    def test_dependencies_checked_without_install(self):
        with patch('importlib.import_module',side_effect=ImportError):
            with self.assertRaisesRegex(RuntimeError,'PACKAGE_DEPENDENCY_MISSING'):
                management_payload.dependencies()
    def test_healthy_services_restore_only_original_active(self):
        before={n:{'ActiveState':'inactive'} for n in (*planner.MANAGEMENT,*planner.TIMERS)}
        before['bridge-graphql.service']['ActiveState']='active'
        with patch.object(planner,'control') as control,patch.object(planner,'unit',return_value={'ActiveState':'active'}):
            planner._restore_states(before)
        self.assertEqual([c.args for c in control.call_args_list],[('start','bridge-graphql.service')])

    def test_native_dns_does_not_require_legacy_release_or_dns_units(self):
        from types import SimpleNamespace
        from bridge_m4.deployment_profile import POLICY_UNITS
        absent={'LoadState':'not-found','ActiveState':'inactive','MainPID':'0','ControlPID':'0','UnitFileState':''}
        output='\n'.join(k+'='+v for k,v in absent.items())
        def control(*args):
            value=absent if not args[1].endswith('.timer') else {k:v for k,v in absent.items() if k not in {'MainPID','ControlPID'}}
            return SimpleNamespace(stdout='\n'.join(k+'='+v for k,v in value.items()))
        with patch('bridge_m4.deployment_profile.load',return_value=None),patch('bridge_m4.dns_sync_runtime.read_status',return_value=({'state':'running','configSha256':'x'},'x')),patch('bridge_m4.native_dns_health.address',return_value='192.0.2.1'),patch('bridge_m4.deployment_profile.show',return_value=absent),patch.object(planner,'control',side_effect=control):
            result=planner.deployment()
        self.assertEqual(result['dnsOwnership'],'native-dae')
        self.assertEqual(result['policyDnsUnits'],[])
    def test_native_dns_refuses_live_retired_unit(self):
        from types import SimpleNamespace
        absent={'LoadState':'not-found','ActiveState':'inactive','MainPID':'0','ControlPID':'0','UnitFileState':''}
        output='LoadState=loaded\nActiveState=active\nMainPID=123\nControlPID=0\nUnitFileState=enabled'
        with patch('bridge_m4.deployment_profile.load',return_value=None),patch('bridge_m4.dns_sync_runtime.read_status',return_value=({'state':'running','configSha256':'x'},'x')),patch('bridge_m4.native_dns_health.address',return_value='192.0.2.1'),patch('bridge_m4.deployment_profile.show',return_value=absent),patch.object(planner,'control',return_value=SimpleNamespace(stdout=output)):
            with self.assertRaisesRegex(RuntimeError,'UPGRADE_RETIRED_DNS_ACTIVE'):
                planner.deployment()

    def test_unknown_or_invalid_sealed_extension_refused(self):
        from types import SimpleNamespace
        for code,version in ((0,'3'),(1,'1')):
            with patch.object(planner.subprocess,'run',return_value=SimpleNamespace(returncode=code,stdout=version)):
                with self.assertRaisesRegex(RuntimeError,'UNSUPPORTED_EXTENSION_STATE'):
                    planner.validate_extensions('/opt/release')
    def test_existing_sealed_extension_formats_accepted(self):
        from types import SimpleNamespace
        for version in ('1','2'):
            with patch.object(planner.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=version)):
                planner.validate_extensions('/opt/release')
