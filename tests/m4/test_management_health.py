import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from bridge_m4 import management_health as health


class ManagementHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(health, 'STATE', root/'state.json'),
                        patch.object(health, 'WEB_CONTROL', root/'client'/'management-recovery'),
                        patch.object(health, 'WEB_PAUSE', root/'client'/'management-recovery'/'pause.json'),
                        patch.object(health, 'WEB_RESUME', root/'client'/'management-recovery'/'resume.json'),
                        patch.object(health, 'LEGACY_PAUSE', root/'legacy-pause'),
                        ]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def write_state(self, *, healthy=True, completed=100):
        services={name:{'healthy':healthy,'checkedAt':completed,
                        'activeState':'active' if healthy else 'failed',
                        'subState':'running' if healthy else 'failed',
                        'mainPid':123 if healthy else 0,'consecutiveFailures':0}
                  for name in health.COMPONENTS}
        health.STATE.write_text(json.dumps({'schemaVersion':1,'services':services,
            'history':[{'at':99,'event':'RECOVERY_SUCCEEDED','service':'daed-web.service',
                        'recovered':True,'needsAttention':False}],
            'lastCheckCompletedAt':completed,'lastCheckResult':'HEALTHY'}))

    def test_healthy_status_is_chinese_and_reports_no_fake_notification(self):
        self.write_state()
        value=health.status(now=120)
        self.assertEqual(value['overall'],'HEALTHY')
        self.assertFalse(value['needsAttention'])
        self.assertIsNone(value['notification']['activeChannel'])
        self.assertEqual(len(value['components']),5)
        self.assertEqual(value['lastRecovery']['title'],'官方 daed 页面')

    def test_stale_state_fails_closed(self):
        self.write_state(completed=100)
        value=health.status(now=1000)
        self.assertEqual(value['overall'],'UNKNOWN')
        self.assertTrue(value['needsAttention'])
        self.assertFalse(any(item['healthy'] for item in value['components']))

    def test_pause_and_resume_use_bridge_owned_marker(self):
        self.write_state()
        value=health.set_paused(True,now=120)
        self.assertTrue(value['paused']);self.assertTrue(health.WEB_PAUSE.is_file())
        self.assertEqual(stat.S_IMODE(health.WEB_PAUSE.parent.stat().st_mode),0o770)
        marker=json.loads(health.WEB_PAUSE.read_text())
        self.assertEqual(marker['pausedAt'],120)
        value=health.set_paused(False,now=121)
        self.assertTrue(value['paused']);self.assertTrue(value['resumePending'])
        self.assertTrue(health.WEB_PAUSE.exists());self.assertTrue(health.WEB_RESUME.exists())

    def test_resume_requires_a_real_pause_marker(self):
        self.write_state()
        with self.assertRaisesRegex(Exception,'MANAGEMENT_RECOVERY_NOT_PAUSED'):
            health.set_paused(False,now=121)


if __name__ == '__main__': unittest.main()
