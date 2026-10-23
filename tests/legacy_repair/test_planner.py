"""Planner compatibility and schema boundaries for automatic payloads."""
import unittest
from scripts import release_management_plan as planner
from tests.legacy_repair.test_payload_upgrade import PayloadUpgradeTests

class PlanTests(PayloadUpgradeTests):
    def test_no_fixed_manifest_count(self):
        for n in range(13):
            self.old['files']['/opt/bridge/vendor/fixture-'+str(n)]={'sha256':'a'*64,'mode':0o644}
        self.assertEqual(self.plan()['changes'],[])
    def test_no_dataplane_restart(self):
        p=self.plan();self.assertFalse(p['restartDae']);self.assertTrue(p['preserveOfficialBinaries'])
    def test_old_entrypoint_delegates_to_same_planner(self):
        from scripts import release_management_upgrade as legacy
        from unittest.mock import patch
        with patch.object(planner,'main',return_value=0) as entry:
            self.assertEqual(legacy.main(['--plan']),0)
        entry.assert_called_once_with(['--plan'])
