import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bridge_m4 import advisory, recovery_budget as budget, recovery_state
from bridge_m4 import management_health as health
from bridge_m4 import maintenance_state as primary, deployment_profile as layout
from bridge_m4 import extension_contracts as contracts, native_dns_health as native
from integration.ui_matrix import evidence_scope as scope
from integration.packaging.cross_version import verify_pair, isolated


def dump(path, value, mode=0o600):
    path.write_text(json.dumps(value));path.chmod(mode)


class Temp(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)


class AdvisoryTests(Temp):
    def test_missing_history_is_not_failure(self):
        self.assertEqual(advisory.optional_json(self.root/'missing'), (None,None))

    def test_corrupt_json_is_warning_not_exception(self):
        p=self.root/'bad';p.write_bytes(b'{');p.chmod(0o600)
        self.assertEqual(advisory.optional_json(p),(None,'HISTORY_UNAVAILABLE'))

    def test_nonobject_history_is_warning(self):
        for value in ([],None,42,True):
            dump(self.root/'x',value)
            self.assertEqual(advisory.optional_json(self.root/'x')[1],'HISTORY_UNAVAILABLE')

    def test_duplicate_and_nonfinite_keys_rejected(self):
        for text in ('{"a":1,"a":2}','{"a":NaN}'):
            (self.root/'x').write_text(text);(self.root/'x').chmod(0o600)
            self.assertEqual(advisory.optional_json(self.root/'x')[1],'HISTORY_UNAVAILABLE')

    def test_symlinks_never_followed(self):
        dump(self.root/'actual',{'secret':'must-not-read'})
        (self.root/'link').symlink_to('actual')
        self.assertEqual(advisory.optional_json(self.root/'link')[1],'HISTORY_UNAVAILABLE')

    def test_world_writable_history_rejected(self):
        dump(self.root/'x',{},0o666)
        self.assertEqual(advisory.optional_json(self.root/'x')[1],'HISTORY_UNAVAILABLE')

    def test_bounded_size(self):
        dump(self.root/'x',{'x':'a'*100})
        self.assertEqual(advisory.optional_json(self.root/'x',limit=10)[1],'HISTORY_UNAVAILABLE')

    def test_missing_old_preview_does_not_block_new_diff(self):
        dump(self.root/'last-applied.json',{'previewId':'a'*64})
        r=advisory.preview_differences(self.root,None,{'nodes':[]},{'records':{}})
        self.assertFalse(r['available']);self.assertIsNone(r['daed'])

    def test_corrupt_marker_does_not_fabricate_zero_changes(self):
        (self.root/'last-applied.json').write_text('{');(self.root/'last-applied.json').chmod(0o600)
        r=advisory.preview_differences(self.root,None,{}, {})
        self.assertEqual(r['baseline'],'history-unavailable')
        self.assertIsNone(r['daeExtensions'])

    def test_new_empty_baseline_is_explicit(self):
        r=advisory.preview_differences(self.root,None,{'nodes':[]},{})
        self.assertTrue(r['available']);self.assertEqual(r['baseline'],'empty')

    def test_valid_historical_snapshot_has_its_own_hash(self):
        values={'source-snapshot.json':b'{"nodes":[]}', 'normalized-ir.json':b'{"extensions":{}}'}
        manifest={'files':{n:{'sha256':hashlib.sha256(b).hexdigest(),'size':len(b)} for n,b in values.items()}}
        raw=json.dumps(manifest).encode();identity=hashlib.sha256(raw).hexdigest()
        folder=self.root/'previews'/identity;folder.mkdir(parents=True,mode=0o700)
        for n,b in {**values,'manifest.json':raw}.items():
            (folder/n).write_bytes(b);(folder/n).chmod(0o600)
        dump(self.root/'last-applied.json',{'previewId':identity})
        r=advisory.preview_differences(self.root,None,{'nodes':[]},{})
        self.assertTrue(r['available']);self.assertEqual(r['daed']['changeCount'],0)
        (folder/'source-snapshot.json').write_bytes(b'{"nodes":[1]}')
        self.assertFalse(advisory.preview_differences(self.root,None,{}, {})['available'])

    def test_idempotency_requires_live_configuration_and_source_identity(self):
        b=b'candidate';(self.root/'candidate.dae').write_bytes(b)
        pending={'directory':self.root,'pins':{'sourceSha256':'b'*64}}
        s={'state':'running','identityVerified':True,'activeBundle':'a'*64,
           'sourceFingerprint':'b'*64,'configSha256':hashlib.sha256(b).hexdigest()}
        self.assertTrue(advisory.already_current(s,pending))
        for changed in ({'sourceFingerprint':'c'*64},{'configSha256':'0'*64},
                        {'identityVerified':False},{'state':'stopped'},{'error':'BUSY'}):
            self.assertFalse(advisory.already_current({**s,**changed},pending))


class BudgetTests(unittest.TestCase):
    def test_two_attempts_and_no_third(self):
        r={}
        self.assertTrue(budget.consume(r,100,observed=('boot',100)))
        self.assertTrue(budget.consume(r,101,observed=('boot',101)))
        self.assertFalse(budget.consume(r,102,observed=('boot',102)))

    def test_monotonic_window_expires(self):
        r={};budget.consume(r,100,observed=('boot',100));budget.consume(r,101,observed=('boot',101))
        self.assertTrue(budget.consume(r,1001,observed=('boot',1001)))

    def test_clock_rollback_does_not_extend_window(self):
        r={};budget.consume(r,5000,observed=('boot',100));budget.consume(r,5001,observed=('boot',101))
        self.assertFalse(budget.permitted(r,2,observed=('boot',102)))
        self.assertTrue(budget.permitted(r,3,observed=('boot',1002)))

    def test_legacy_future_timestamp_gets_one_bounded_hold(self):
        r={'attempts':[999999999]}
        self.assertFalse(budget.permitted(r,100,observed=('boot',10)))
        self.assertFalse(budget.permitted(r,1,observed=('boot',909)))
        self.assertTrue(budget.permitted(r,2,observed=('boot',910)))

    def test_reboot_conservative_then_finite(self):
        r={};budget.consume(r,100,observed=('a',500))
        self.assertFalse(budget.permitted(r,200,observed=('b',5)))
        self.assertTrue(budget.permitted(r,300,observed=('b',905)))

    def test_corrupt_budget_does_not_reset_to_unlimited(self):
        for r in ({'retryBudget':[]},{'attempts':['bad']},{'attempts':[True]}):
            self.assertFalse(budget.permitted(r,100,observed=('a',10)))
            self.assertTrue(budget.permitted(r,101,observed=('a',910)))

    def test_unknown_history_holds_without_mutating_services(self):
        r={};self.assertFalse(budget.permitted(r,100,observed=('a',10),uncertain=True))
        self.assertEqual(r['retryBudget']['holdUntil'],910)


class RecoveryHistoryTests(Temp):
    def test_bad_history_returns_fresh_probe_records(self):
        p=self.root/'state';p.write_text('{');p.chmod(0o600)
        value=recovery_state.load(p,['current.service'],100,observed=('boot',10))
        self.assertIn('current.service',value['services'])
        self.assertEqual(value['historyWarning'],'HISTORY_UNAVAILABLE')
        self.assertFalse(budget.permitted(value['services']['current.service'],100,observed=('boot',10)))
        self.assertEqual((self.root/'state.rejected').read_text(),'{')

    def test_corrupt_copy_is_bounded_and_not_overwritten(self):
        p=self.root/'state';p.write_text('{');p.chmod(0o600)
        recovery_state.load(p,['a'],100,observed=('boot',10))
        p.write_text('[')
        recovery_state.load(p,['a'],101,observed=('boot',11))
        self.assertEqual((self.root/'state.rejected').read_text(),'{')
        self.assertEqual(len(list(self.root.iterdir())),2)

    def test_retired_service_history_is_retained_not_aggregated(self):
        p=self.root/'state';dump(p,{'schemaVersion':1,'services':{'retired':{'healthy':False}},'history':[]})
        value=recovery_state.load(p,['current'],100,observed=('boot',10))
        value['services']['current']['healthy']=True
        self.assertTrue(all(value['services'][n]['healthy'] is True for n in ['current']))
        self.assertIn('retired',value['services'])

    def test_invalid_current_record_preserves_rate_safety(self):
        p=self.root/'state';dump(p,{'schemaVersion':1,'services':{'a':[]},'history':[]})
        value=recovery_state.load(p,['a'],100,observed=('boot',10))
        self.assertFalse(budget.permitted(value['services']['a'],100,observed=('boot',10)))


class HealthTests(Temp):
    def setUp(self):
        super().setUp()
        for key in ('STATE','WEB_PAUSE','WEB_RESUME','LEGACY_PAUSE'):
            p=patch.object(health,key,self.root/key);p.start();self.addCleanup(p.stop)

    def state(self):
        return {'schemaVersion':1,'lastCheckCompletedAt':100,'services':{
            name:{'healthy':True,'checkedAt':100,'lastRecoverySucceeded':False,'consecutiveFailures':0}
            for name in health.COMPONENTS},'history':[]}

    def test_old_failure_is_not_current_alert(self):
        dump(health.STATE,self.state());s=health.status(now=101)
        self.assertEqual(s['overall'],'HEALTHY');self.assertFalse(s['needsAttention'])
        self.assertTrue(all(x['lastRecoverySucceeded'] is False for x in s['components']))

    def test_current_failure_remains_attention(self):
        v=self.state();v['services'][next(iter(health.COMPONENTS))]['healthy']=False
        dump(health.STATE,v);self.assertEqual(health.status(now=101)['overall'],'ATTENTION_REQUIRED')

    def test_stale_history_is_unknown_not_healthy(self):
        dump(health.STATE,self.state());self.assertEqual(health.status(now=1000)['overall'],'UNKNOWN')

    def test_bad_history_does_not_crash_page(self):
        health.STATE.write_text('{');health.STATE.chmod(0o600)
        self.assertEqual(health.status(now=101)['overall'],'UNKNOWN')

    def test_retired_service_cannot_contaminate_current_health(self):
        v=self.state();v['services']['retired.service']={'healthy':False,'lastRecoverySucceeded':False}
        dump(health.STATE,v);self.assertEqual(health.status(now=101)['overall'],'HEALTHY')

    def test_pause_is_not_misrepresented_as_running_recovery(self):
        dump(health.STATE,self.state());health.WEB_PAUSE.write_text('{}')
        self.assertEqual(health.status(now=101)['overall'],'PAUSED')


class LayoutTests(unittest.TestCase):
    def states(self):
        return {name:{'LoadState':'masked','ActiveState':'failed','MainPID':'0','ControlPID':'0','UnitFileState':'masked'}
                for name in layout.POLICY_UNITS}
    def profile(self):
        return {'schemaVersion':1,'layoutVersion':1,'dnsOwnership':'native-dae','policyDnsUnits':[]}

    def test_declared_native_ignores_retired_failed_latch(self):
        self.assertFalse(layout.selected_policy_dns(self.profile(),self.states()))

    def test_native_cannot_ignore_live_old_consumer(self):
        states=self.states();states[layout.POLICY_UNITS[0]]['ActiveState']='active'
        with self.assertRaisesRegex(RuntimeError,'UNDECLARED'):layout.selected_policy_dns(self.profile(),states)

    def test_enabled_old_consumer_is_not_proven_retired(self):
        states=self.states();states[layout.POLICY_UNITS[0]]['UnitFileState']='enabled'
        with self.assertRaises(RuntimeError):layout.selected_policy_dns(self.profile(),states)

    def test_selected_consumer_failure_still_blocks(self):
        p={**self.profile(),'dnsOwnership':'bridge-managed','policyDnsUnits':['bridge-policy-dns.service']}
        with self.assertRaisesRegex(RuntimeError,'NOT_HEALTHY'):layout.selected_policy_dns(p,self.states())

    def test_absent_profile_keeps_legacy_failure_closed(self):
        with self.assertRaisesRegex(RuntimeError,'NOT_HEALTHY'):layout.selected_policy_dns(None,self.states())

    def test_native_units_never_include_retired_dns(self):
        self.assertEqual(layout.lifecycle_units(('dae.service','independent-policy-sync.timer'),self.profile()),('dae.service',))

    def test_invalid_ownership_schema_rejected(self):
        with self.assertRaises(RuntimeError):layout.validate({**self.profile(),'policyDnsUnits':['arbitrary.service']})


class PrimaryTests(unittest.TestCase):
    def fixture(self):
        a={'attemptId':'synthetic-attempt','candidateSha':'a'*40,'rollbackManifestSha256':'b'*64,
           'databaseSha256':'c'*64,'activeBundle':'d'*64}
        tx={**a,'phase':'phase2','deadline':100,'rollbackRequired':False,'checkpoint':'PHASE2_ACCEPTED',
            'phase1Accepted':True,'finalAccepted':True,'rollbackResult':None}
        def bind(phase):return {'attemptId':a['attemptId'],'phase':phase,'primaryVersion':'primary-7ed6de2-v7','candidateSha':a['candidateSha'],
            'manifestSha256':a['rollbackManifestSha256'],'databaseSha256':a['databaseSha256'],'bundleSha256':a['activeBundle']}
        evidence={'attemptId':a['attemptId'],'candidateSha':a['candidateSha'],'activeBundle':a['activeBundle'],
                  'passed':True,'checks':{n:True for n in ('identity','configuration','dns','tcp','udp','kernel','web','singleDataPlane')}}
        records={}
        for p,f in (('phase1','phase1-accepted.json'),('phase2','final-accepted.json')):
            records[p+'-armed.json']={**bind(p),'deadline':100}
            records[f]={**bind(p),'deadline':100,'evidence':evidence}
        units={f'primary-rollback-{p}.{k}':{'LoadState':'loaded','ActiveState':'inactive','MainPID':'0','ControlPID':'0',
                'UnitFileState':'disabled','NextElapseUSecRealtime':'0','NextElapseUSecMonotonic':'0'}
               for p in ('phase1','phase2') for k in ('timer','service')}
        return a,tx,records,units

    def test_completed_matching_attempt_is_historical(self):
        self.assertTrue(primary.completed_snapshot(*self.fixture()))

    def test_armed_timer_still_blocks_completed_marker(self):
        a,t,r,u=self.fixture();u['primary-rollback-phase2.timer']['ActiveState']='active'
        with self.assertRaises(RuntimeError):primary.completed_snapshot(a,t,r,u)

    def test_wrong_attempt_binding_blocks(self):
        a,t,r,u=self.fixture();r['final-accepted.json']['attemptId']='other'
        with self.assertRaises(RuntimeError):primary.completed_snapshot(a,t,r,u)

    def test_explicit_rollback_required_blocks(self):
        a,t,r,u=self.fixture();t['rollbackRequired']=True
        with self.assertRaises(RuntimeError):primary.completed_snapshot(a,t,r,u)

    def test_missing_final_acceptance_blocks(self):
        a,t,r,u=self.fixture();del r['final-accepted.json']
        with self.assertRaises(RuntimeError):primary.completed_snapshot(a,t,r,u)

    def test_scheduled_but_inactive_timer_blocks(self):
        a,t,r,u=self.fixture();u['primary-rollback-phase1.timer']['NextElapseUSecMonotonic']='500'
        with self.assertRaises(RuntimeError):primary.completed_snapshot(a,t,r,u)

    def test_partial_acceptance_never_becomes_terminal(self):
        a,t,r,u=self.fixture();r['final-accepted.json']['evidence']['checks']['dns']=False
        with self.assertRaises(RuntimeError):primary.completed_snapshot(a,t,r,u)


class ContractsTests(Temp):
    def model(self):
        values={'Global':{'mptcp':{'type':'bool','default':'false','required':False}},'Dns':{},'Group':{}}
        return {'source':{'models':copy.deepcopy(values)},'target':{'models':copy.deepcopy(values)}}

    def test_section_identity_ignores_other_sections(self):
        old=self.model();new=copy.deepcopy(old);new['target']['models']['Dns']['extra']={'type':'int'}
        self.assertEqual(contracts.section_identity(old,'global'),contracts.section_identity(new,'global'))
        self.assertTrue(contracts.compatible('global',old,new))

    def test_v2_uses_trusted_archived_original_model(self):
        old=self.model();new=copy.deepcopy(old);new['target']['models']['Dns']['extra']={'type':'int'}
        pin=contracts.identity(old);(self.root/(pin+'.json')).write_text(json.dumps(old))
        record={'schemaVersion':2,'section':'global','contractSha256':pin}
        self.assertEqual(contracts.resolve(record,new,{},archive=self.root),old)

    def test_v2_unknown_contract_is_not_guessed(self):
        r={'schemaVersion':2,'section':'global','contractSha256':'f'*64}
        with self.assertRaises(FileNotFoundError):contracts.resolve(r,self.model(),{},archive=self.root)

    def test_archive_tampering_is_rejected(self):
        old=self.model();pin=contracts.identity(old);(self.root/(pin+'.json')).write_text('{}')
        r={'schemaVersion':2,'section':'global','contractSha256':pin}
        with self.assertRaises(ValueError):contracts.resolve(r,{}, {},archive=self.root)

    def test_v3_does_not_need_a_dns_only_migration(self):
        old=self.model();new=copy.deepcopy(old);new['target']['models']['Dns']['extra']={'type':'int'}
        r={'schemaVersion':3,'section':'global','sectionContractSha256':contracts.section_identity(old,'global')}
        self.assertEqual(contracts.resolve(r,new,old),new)

    def test_added_field_requires_reviewed_rule(self):
        old=self.model();new=copy.deepcopy(old);new['target']['models']['Global']['extra']={'type':'int','default':'0','required':False}
        rules=self.root/'rules';dump(rules,{'schemaVersion':1,'rules':{}})
        self.assertFalse(contracts.compatible('global',old,new,rules_path=rules))
        key=contracts.section_identity(old,'global')+':'+contracts.section_identity(new,'global')
        dump(rules,{'schemaVersion':1,'rules':{key:{'section':'global','addedAbsentFields':['extra'],'review':'synthetic review only'}}})
        self.assertTrue(contracts.compatible('global',old,new,rules_path=rules))

    def test_default_type_or_ownership_change_not_silently_compatible(self):
        for change in ('default','type','required'):
            old=self.model();new=copy.deepcopy(old);new['target']['models']['Global']['mptcp'][change]='different'
            self.assertFalse(contracts.compatible('global',old,new,rules_path=self.root/'absent'))

    def test_contract_path_traversal_rejected(self):
        with self.assertRaises(ValueError):contracts.resolve({'schemaVersion':2,'section':'global','contractSha256':'../x'},self.model(),{})


class NativeTests(unittest.TestCase):
    def table(self,protocol,inode='42',address='00000000',port='0035'):
        state='0A' if protocol=='tcp' else '07'
        return 'head\n0: '+address+':'+port+' 00000000:0000 '+state+' 0:0 0:0 0 0 0 '+inode+'\n'
    def test_both_protocols_must_be_owned(self):
        tables=[(p,self.table(p)) for p in ('tcp','udp')]
        self.assertEqual(native.owned_protocols(tables,{'42'},'192.0.2.1'),{'tcp','udp'})
        self.assertEqual(native.owned_protocols(tables,{'99'},'192.0.2.1'),set())
    def test_other_port_is_not_dns_proof(self):
        self.assertEqual(native.owned_protocols([('tcp',self.table('tcp',port='14E9'))],{'42'},'192.0.2.1'),set())
    def test_tcp_alone_is_not_udp_proof(self):
        self.assertEqual(native.owned_protocols([('tcp',self.table('tcp'))],{'42'},'192.0.2.1'),{'tcp'})


class EvidenceTests(Temp):
    def setUp(self):
        super().setUp();self.source=self.root/'src';self.source.mkdir();self.evidence=self.root/'ev';self.evidence.mkdir()
        (self.source/'upstream.lock.json').write_text('{}')
        (self.source/'bridge_m4').mkdir();(self.source/'bridge_m4/a.py').write_text('x=1\n')
        (self.source/'upgrade.sh').write_text('exit 0\n')
    def test_new_run_does_not_see_old_pass(self):
        (self.evidence/'result.json').write_text('[{"passed":true}]')
        a=scope.start_run(self.source,self.evidence,boot='a')
        p=scope.scope_file(self.evidence/'result.json',root=self.source,evidence=self.evidence,boot='a')
        self.assertFalse(p.exists());self.assertIn(a['runId'],str(p))
    def test_changed_source_rejects_resume(self):
        scope.start_run(self.source,self.evidence,boot='a');(self.source/'bridge_m4/a.py').write_text('x=2\n')
        with self.assertRaisesRegex(RuntimeError,'CONTEXT_CHANGED'):scope.current(self.source,self.evidence,boot='a')
    def test_reboot_rejects_resume(self):
        scope.start_run(self.source,self.evidence,boot='a')
        with self.assertRaises(RuntimeError):scope.current(self.source,self.evidence,boot='b')
    def test_fresh_run_retains_old_namespace(self):
        a=scope.start_run(self.source,self.evidence,boot='a');b=scope.start_run(self.source,self.evidence,boot='a')
        self.assertNotEqual(a['runId'],b['runId']);self.assertEqual(len(list((self.evidence/'runs').iterdir())),2)
    def test_same_source_is_not_cross_version(self):
        with self.assertRaisesRegex(RuntimeError,'DISTINCT'):verify_pair(self.source,self.source)
    def test_different_source_is_recorded_with_hashes(self):
        import shutil
        other=self.root/'other';shutil.copytree(self.source,other);(other/'bridge_m4/a.py').write_text('x=2\n')
        pair=verify_pair(self.source,other)
        self.assertNotEqual(pair['beforeTreeSha256'],pair['afterTreeSha256']);self.assertFalse(pair['officialArtifactsChanged'])
    def test_guest_guard_refuses_current_container(self):
        with patch('integration.packaging.cross_version.Path.is_file',return_value=False):
            with self.assertRaises(RuntimeError):isolated()

if __name__=='__main__':unittest.main()
