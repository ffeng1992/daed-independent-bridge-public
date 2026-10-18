import unittest
from bridge_m4.auth import Sessions,AuthError

class Authority:
    def __init__(self):self.revoked=False
    def login(self,value):
        if value!={'token':'synthetic-token'}:raise AuthError('AUTH_FAILED')
        return 'synthetic-token'
    def verify(self,token):
        if self.revoked or token!='synthetic-token':raise AuthError('AUTH_FAILED')

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.time=10.;self.authority=Authority();self.sessions=Sessions(self.authority,now=lambda:self.time)
    def login(self):
        c=self.sessions.challenge();return self.sessions.login(c,c,{'token':'synthetic-token'},'synthetic-peer')
    def test_authentication(self):
        sid,csrf=self.login();token,_=self.sessions.authorized(sid)
        self.assertTrue(token=='synthetic-token');self.assertNotIn(sid,self.sessions.sessions)
    def test_replay_rejected(self):
        sid,csrf=self.login();_,next_csrf=self.sessions.authorized(sid,csrf,True)
        self.assertNotEqual(csrf,next_csrf)
        with self.assertRaisesRegex(AuthError,'CSRF_REJECTED'):self.sessions.authorized(sid,csrf,True)
        self.sessions.authorized(sid,next_csrf,True)
    def test_challenge_replay(self):
        c=self.sessions.challenge();self.sessions.login(c,c,{'token':'synthetic-token'},'peer')
        with self.assertRaisesRegex(AuthError,'CSRF_REJECTED'):self.sessions.login(c,c,{'token':'synthetic-token'},'peer')
    def test_expiry(self):
        sid,_=self.login();self.time+=300
        with self.assertRaisesRegex(AuthError,'UNAUTHORIZED'):self.sessions.authorized(sid)
    def test_logout(self):
        sid,_=self.login();self.sessions.logout(sid)
        with self.assertRaisesRegex(AuthError,'UNAUTHORIZED'):self.sessions.authorized(sid)
    def test_revocation(self):
        sid,_=self.login();self.authority.revoked=True
        with self.assertRaisesRegex(AuthError,'UNAUTHORIZED'):self.sessions.authorized(sid)
    def test_failed_login_has_no_session(self):
        c=self.sessions.challenge()
        with self.assertRaisesRegex(AuthError,'AUTH_FAILED'):self.sessions.login(c,c,{'token':'wrong'},'peer')
        self.assertEqual(len(self.sessions.sessions),0)
    def test_rate_limit(self):
        for _ in range(5):
            c=self.sessions.challenge()
            with self.assertRaisesRegex(AuthError,'AUTH_FAILED'):self.sessions.login(c,c,{'token':'wrong'},'peer')
        c=self.sessions.challenge()
        with self.assertRaisesRegex(AuthError,'AUTH_RATE_LIMIT'):self.sessions.login(c,c,{'token':'synthetic-token'},'peer')
    def test_bad_csrf_does_not_authenticate(self):
        c=self.sessions.challenge()
        with self.assertRaisesRegex(AuthError,'CSRF_REJECTED'):self.sessions.login(c,'wrong',{'token':'synthetic-token'},'peer')

    def test_malformed_session_identifiers_fail_closed(self):
        for value in (None, [], {}, 1, 'x'*8193):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(AuthError):self.sessions.authorized(value)
    def test_non_ascii_csrf_is_rejected(self):
        sid,_=self.login()
        with self.assertRaisesRegex(AuthError,'CSRF_REJECTED'):self.sessions.authorized(sid,'合成',True)
    def test_session_repr_omits_secrets(self):
        sid,csrf=self.login()
        rendered=repr(self.sessions.sessions[self.sessions.key(sid)])
        self.assertNotIn('synthetic-token',rendered)
        self.assertNotIn(csrf,rendered)
    def test_invalid_ttl(self):
        for ttl in (True,0,901,1.5,'300'):
            with self.assertRaises(AuthError):Sessions(self.authority,ttl=ttl)
