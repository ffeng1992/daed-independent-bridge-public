import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import management_recovery as m


class ManagementRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(m, 'STATE', root/'state.json'),
                        patch.object(m, 'PAUSE', root/'pause'),
                        patch.object(m, 'WEB_CONTROL', root/'web-control'),
                        patch.object(m, 'WEB_PAUSE', root/'web-control'/'pause.json'),
                        patch.object(m, 'WEB_RESUME', root/'web-control'/'resume.json')]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def run_checks(self, health, actions, times=(100, 161)):
        def healthy(name, kind): return (health.get(name, False), 'DOWN')
        def show(name): return {'ActiveState':'active' if health.get(name) else 'inactive'}
        def ctl(action, name):
            actions.append((action, name)); health[name] = True
        with patch.object(m, 'locks', return_value=[]), patch.object(m, 'maintenance_guard'), \
             patch.object(m, 'healthy', side_effect=healthy), patch.object(m, 'show', side_effect=show), \
             patch.object(m, 'systemctl', side_effect=ctl):
            for now in times: m.check_once(now)

    def test_normal_stop_requires_two_failures_then_starts_only_target(self):
        health = {name: True for name, _ in m.SERVICES}; health['daed-web.service'] = False
        actions=[]; self.run_checks(health, actions)
        self.assertEqual(actions, [('start','daed-web.service')])

    def test_active_http_hang_restarts_only_target(self):
        health={name:True for name,_ in m.SERVICES}; actions=[]
        calls={'n':0}
        def check(name, kind):
            if name=='bridge-graphql.service' and calls['n']<2:
                calls['n']+=1; return False,'HTTP_STATUS'
            return True,''
        with patch.object(m,'locks',return_value=[]),patch.object(m,'maintenance_guard'), \
             patch.object(m,'healthy',side_effect=check),patch.object(m,'show',return_value={'ActiveState':'active'}), \
             patch.object(m,'systemctl',side_effect=lambda a,n:actions.append((a,n))):
            m.check_once(100);m.check_once(161)
        self.assertEqual(actions,[('restart','bridge-graphql.service')])

    def test_api_and_dependency_cascade_restore_in_dependency_order(self):
        health={name:False for name,_ in m.SERVICES};health['independent-bridge.service']=True
        actions=[];self.run_checks(health,actions)
        self.assertEqual([name for _,name in actions],
                         ['daed-api.service','bridge-graphql.service','bridge-attestor.service','daed-web.service'])

    def test_pause_skips_every_action(self):
        m.PAUSE.write_text('paused')
        actions=[]
        with patch.object(m,'locks',return_value=[]),patch.object(m,'systemctl',side_effect=lambda *x:actions.append(x)):
            m.check_once(100)
        self.assertEqual(actions,[])

    def test_install_identity_failure_skips_every_action(self):
        actions=[]
        with patch.object(m,'locks',return_value=[]),patch.object(m,'maintenance_guard',side_effect=RuntimeError('INSTALL_FILE_IDENTITY')), \
             patch.object(m,'systemctl',side_effect=lambda *x:actions.append(x)):
            m.check_once(100)
        self.assertEqual(actions,[])

    def test_rate_limit_stops_third_recovery(self):
        state={'schemaVersion':1,'services':{'daed-web.service':{'consecutiveFailures':2,'attempts':[10,20]}}}
        m.STATE.write_text(json.dumps(state))
        actions=[]
        with patch.object(m,'locks',return_value=[]),patch.object(m,'maintenance_guard'), \
             patch.object(m,'healthy',return_value=(False,'DOWN')),patch.object(m,'show',return_value={'ActiveState':'inactive'}), \
             patch.object(m,'systemctl',side_effect=lambda *x:actions.append(x)):
            m.check_once(100)
        self.assertEqual(actions,[])

    def test_healthy_check_has_no_service_action(self):
        health={name:True for name,_ in m.SERVICES};actions=[];self.run_checks(health,actions,times=(100,))
        self.assertEqual(actions,[])

    def test_read_only_probes_do_not_hold_apply_lock(self):
        order=[]
        def health(name, kind):
            self.assertEqual(order[-1], 'locks-closed')
            return True, ''
        with patch.object(m, 'locks', side_effect=lambda: order.append('locks-open') or [123]), \
             patch.object(m, 'close_locks', side_effect=lambda _: order.append('locks-closed')), \
             patch.object(m, 'maintenance_guard'), patch.object(m, 'healthy', side_effect=health), \
             patch.object(m, 'show', return_value={'ActiveState':'active','MainPID':'123'}):
            m.check_once(100)
        self.assertEqual(order, ['locks-open', 'locks-closed'])

    def test_apply_lock_busy_skips_recovery_without_service_action(self):
        state={'schemaVersion':1,'services':{'daed-web.service':{'consecutiveFailures':1}}}
        m.STATE.write_text(json.dumps(state)); actions=[]; calls={'locks':0}
        def lock_probe():
            calls['locks'] += 1
            if calls['locks'] > 1: raise BlockingIOError('apply-active')
            return []
        with patch.object(m, 'locks', side_effect=lock_probe), patch.object(m, 'maintenance_guard'), \
             patch.object(m, 'healthy', return_value=(False,'DOWN')), \
             patch.object(m, 'show', return_value={'ActiveState':'inactive','MainPID':'0'}), \
             patch.object(m, 'systemctl', side_effect=lambda *x: actions.append(x)):
            m.check_once(100)
        self.assertEqual(actions, [])

    def test_state_contains_bounded_structured_history_and_live_component_status(self):
        health={name:True for name,_ in m.SERVICES};health['daed-web.service']=False;actions=[]
        self.run_checks(health,actions)
        state=json.loads(m.STATE.read_text())
        self.assertEqual(state['lastCheckResult'],'HEALTHY')
        self.assertTrue(state['services']['daed-web.service']['healthy'])
        self.assertEqual(state['services']['daed-web.service']['mainPid'],0)
        self.assertEqual([x['event'] for x in state['history']],
                         ['SERVICE_HEALTH_FAILED','RECOVERY_SUCCEEDED'])
        for n in range(m.HISTORY_LIMIT+5):m.append_history(state,'TEST',n)
        self.assertEqual(len(state['history']),m.HISTORY_LIMIT)

    def test_web_pause_marker_uses_same_fail_closed_guard(self):
        m.WEB_PAUSE.parent.mkdir()
        m.WEB_PAUSE.write_text('paused')
        actions=[]
        with patch.object(m,'locks',return_value=[]),patch.object(m,'systemctl',side_effect=lambda *x:actions.append(x)):
            m.check_once(100)
        self.assertEqual(actions,[])

    def test_web_resume_is_authorized_by_privileged_guard_then_checks(self):
        m.WEB_PAUSE.parent.mkdir();m.WEB_PAUSE.write_text('{}');m.WEB_RESUME.write_text('{}')
        health={name:True for name,_ in m.SERVICES};actions=[]
        with patch.object(m,'locks',return_value=[]), \
             patch.object(m,'maintenance_guard') as guard, \
             patch.object(m,'healthy',side_effect=lambda n,k:(health[n],'')), \
             patch.object(m,'show',return_value={'ActiveState':'active','MainPID':'123'}), \
             patch.object(m,'systemctl',side_effect=lambda *x:actions.append(x)):
            m.check_once(100)
        guard.assert_any_call(allow_web_paused=True)
        self.assertFalse(m.WEB_PAUSE.exists());self.assertFalse(m.WEB_RESUME.exists())
        self.assertEqual(actions,[])

    def test_web_resume_guard_failure_keeps_pause_and_request(self):
        m.WEB_PAUSE.parent.mkdir();m.WEB_PAUSE.write_text('{}');m.WEB_RESUME.write_text('{}')
        with patch.object(m,'locks',return_value=[]), \
             patch.object(m,'maintenance_guard',side_effect=RuntimeError('ROLLBACK_REQUIRED')):
            self.assertEqual(m.check_once(100),0)
        self.assertTrue(m.WEB_PAUSE.exists());self.assertTrue(m.WEB_RESUME.exists())

    def test_service_uses_bridge_group_without_extra_capability(self):
        unit=(Path(__file__).parents[2]/'deployment/release/units/bridge-management-recovery.service').read_text()
        self.assertIn('Group=independent-bridge\n',unit)
        self.assertIn('CapabilityBoundingSet=\n',unit)
        self.assertIn('/var/lib/bridge-m4-client/management-recovery',unit)

    def test_capture_and_restore_only_previously_active_services(self):
        target=Path(self.temp.name)/'capture.json';actions=[]
        states={name:('active' if name in {'daed-api.service','daed-web.service'} else 'inactive') for name,_ in m.SERVICES}
        with patch.object(m,'show',side_effect=lambda n:{'ActiveState':states[n]}):m.capture(target)
        content=json.loads(target.read_text())
        self.assertTrue(content['services']['daed-api.service']);self.assertFalse(content['services']['bridge-attestor.service'])
        states['daed-api.service']=states['daed-web.service']='inactive'
        def healthy(name, kind): return states[name]=='active','' if states[name]=='active' else 'DOWN'
        def ctl(action,name): actions.append((action,name));states[name]='active'
        with patch.object(m,'maintenance_guard'),patch.object(m,'healthy',side_effect=healthy), \
             patch.object(m,'systemctl',side_effect=ctl):m.restore(target)
        self.assertEqual(actions,[('start','daed-api.service'),('start','daed-web.service')])


if __name__ == '__main__': unittest.main()
