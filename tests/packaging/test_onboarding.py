import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from bridge_m4.auth import AuthError, BridgeAuthenticator, Sessions
from scripts import release_setup as setup, release_lifecycle as lifecycle

ROOT=Path(__file__).resolve().parents[2]

class OnboardingTests(unittest.TestCase):
    def test_installer_has_no_account_or_configuration_mutations(self):
        source=(ROOT/'scripts/release_setup.py').read_text()
        for forbidden in ('createUser','resetpass','updatePassword','createConfig','createDns','createRouting','initial-admin.json'):
            self.assertNotIn(forbidden,source)
        self.assertNotIn('initialize()', (ROOT/'scripts/release_lifecycle.py').read_text())

    def test_bridge_login_does_not_accept_daed_credentials(self):
        auth=BridgeAuthenticator(lambda:'bridge-only-secret')
        self.assertEqual(auth.login({'token':'bridge-only-secret'}),'bridge-only-secret')
        for value in ({'token':'daed-token'},{'username':'admin','password':'password'},{}):
            with self.assertRaises(AuthError):auth.login(value)

    def test_bridge_sessions_survive_daed_unavailability_but_not_key_rotation(self):
        key=['bridge-only-secret'];sessions=Sessions(BridgeAuthenticator(lambda:key[0]))
        c=sessions.challenge();sid,csrf=sessions.login(c,c,{'token':key[0]},'test')
        self.assertEqual(sessions.authorized(sid)[0],key[0])
        key[0]='rotated'
        with self.assertRaises(AuthError):sessions.authorized(sid)

    def test_bridge_token_never_reaches_official_api(self):
        tree=ast.parse((ROOT/'bridge_m4/web.py').read_text())
        collectors=[n for n in ast.walk(tree) if isinstance(n,ast.Lambda)]
        self.assertEqual(len(collectors),1)
        calls=[]
        fn=eval(compile(ast.Expression(collectors[0]),'collector','eval'),{
            'collect':lambda x:x,'HTTPReader':lambda endpoint,token:calls.append((endpoint,token)),
            'ENDPOINT':'loopback','local_token':lambda name:'daed-connection-token'})
        fn('bridge-session-token')
        self.assertEqual(calls,[('loopback','daed-connection-token')])

    def test_bridge_credential_creation_is_separate_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d,patch.object(setup,'CFG',Path(d)),patch.object(setup.pwd,'getpwnam',return_value=SimpleNamespace(pw_gid=123)):
            calls=[]
            def write(path,body,mode,gid):
                calls.append((path.name,mode,gid));path.write_bytes(body)
            with patch.object(setup,'write',side_effect=write),patch.object(setup,'api') as api:
                setup.bridge_credentials();before=(Path(d)/'bridge-login.token').read_bytes()
                setup.bridge_credentials()
                self.assertEqual((Path(d)/'bridge-login.token').read_bytes(),before)
                api.assert_not_called()
            self.assertEqual(calls,[('bridge-login.token',0o640,123)])
            self.assertFalse((Path(d)/'initial-admin.json').exists())

    def test_pending_install_starts_only_management(self):
        with patch.object(lifecycle,'ctl') as ctl:
            lifecycle.start_management()
        for call in ctl.call_args_list:
            for forbidden in ('dae.service','bridge-attestor.service',*lifecycle.TIMERS):
                self.assertNotIn(forbidden,call.args)
        self.assertTrue(any('daed-web.service' in c.args for c in ctl.call_args_list))

    def test_noninteractive_connection_refuses_before_token_request(self):
        with patch.object(lifecycle.sys.stdin,'isatty',return_value=False),patch.object(setup,'api') as api:
            with self.assertRaisesRegex(RuntimeError,'INTERACTIVE_DAED_AUTHORIZATION_REQUIRED'):lifecycle.connect_daed()
            api.assert_not_called()

    def test_official_interface_query_has_unprivileged_netlink(self):
        unit=(ROOT/'deployment/m4/units/daed-api.service').read_text()
        self.assertIn('AF_NETLINK',unit)
        self.assertIn('CapabilityBoundingSet=\n',unit)
        self.assertIn('User=bridge-daed',unit)
        self.assertIn('--api-only',unit)
