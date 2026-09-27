import subprocess
import unittest
from pathlib import Path
from bridge_m4.dnsdist_control import DnsdistControl,parse_servers,SyncError
from bridge_m4.release_policy import generate
from scripts.release_build import included
class DNSTests(unittest.TestCase):
    def test_console_only_no_database(self):
        servers=parse_servers('0 DAE 127.0.0.1:5353 UP 0\n1 DIRECT 192.0.2.53:53 DOWN 0')
        self.assertEqual(servers['DAE'].state,'UP')
        calls=[]
        control=DnsdistControl(('/usr/bin/dnsdist','-c'),lambda args,_:(calls.append(args) or subprocess.CompletedProcess(args,0,'','')))
        control.set_state(servers['DAE'],'DOWN')
        self.assertEqual(calls[-1][-1],'getServer(0):setDown()')
        with self.assertRaises(SyncError):control.set_state(servers['DAE'],'anything')
    def test_ordered_rules_and_unknown_pool(self):
        text=generate("domain(full: 'first.test') -> direct\ndomain(suffix: 'test') -> block\nfallback: direct",{'direct':'192.0.2.53:53'},Path('/unused')).decode()
        self.assertLess(text.index('QNameRule'),text.index('QNameSuffixRule'))
        self.assertIn('DNSRCode.REFUSED',text)
        for rule in ("domain(full: 'a') && dport(443) -> direct\nfallback: direct",'fallback: unknown'):
            with self.assertRaises(ValueError):generate(rule,{'direct':'192.0.2.53:53'},Path('/unused'))
    def test_release_excludes_private_and_experiments(self):
        for name in ('.local/database.sqlite','out/secret.json','integration/m4/seed.py','scripts/primary_rollback_production_v7.py','tests/fixtures.sqlite','.git/config'):
            self.assertFalse(included(name),name)
        for name in ('install.sh','scripts/release_setup.py','bridge_m4/release_dns.py','upstream.lock.json'):
            self.assertTrue(included(name),name)
