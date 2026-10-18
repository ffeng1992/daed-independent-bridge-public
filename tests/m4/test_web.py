import http.client
import json
import threading
import unittest
from bridge_m4.web import Server
from bridge_m4.auth import Sessions
from tests.m4.test_auth import Authority

class Backend:
    def __init__(self):self.calls=[];self.lock=threading.RLock()
    def action(self,a,b=None):self.calls.append((a,b));return {'state':'running','MainPID':123,'activeBundle':'1'*64,'InvocationID':'2'*32}
    def extensions(self):return {'generation':'3'*64,'records':{}}
    def bind_extensions(self,t):self.calls.append(('bind-extensions',t));return {'generation':'3'*64,'changed':False}
    def preview(self,t):self.calls.append(('preview',));return {'previewId':'4'*64}

class Management:
    def __init__(self):self.calls=[];self.paused=False
    def status(self):
        self.calls.append(('status',));return {'overall':'PAUSED' if self.paused else 'HEALTHY'}
    def set_paused(self,value):
        self.calls.append(('set_paused',value));self.paused=value;return self.status()

class WebTests(unittest.TestCase):
    def setUp(self):
        self.backend=Backend();self.authority=Authority();self.management=Management()
        self.server=Server(('127.0.0.1',0),'https://127.0.0.1',Sessions(self.authority),self.backend,self.management)
        self.server.origin='https://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.cookies={};self.csrf=''
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def req(self,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        h={'Cookie':'; '.join(k+'='+v for k,v in self.cookies.items())}
        if body is not None:h.update({'Content-Type':'application/json','Origin':self.server.origin,'X-CSRF-Token':self.csrf})
        h.update(headers or {})
        c.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=h)
        r=c.getresponse();raw=r.read();status=r.status;headers=dict(r.getheaders());c.close()
        if 'Set-Cookie' in headers:
            k,v=headers['Set-Cookie'].split(';')[0].split('=',1);self.cookies[k]=v
        return status,raw,headers
    def login(self):
        status,raw,_=self.req('/api/challenge');self.assertEqual(status,200);self.csrf=json.loads(raw)['csrf']
        status,raw,headers=self.req('/api/login',{'token':'synthetic-token'});self.assertEqual(status,200);self.csrf=json.loads(raw)['csrf'];return headers
    def test_unauthenticated_information_is_blocked(self):
        for route in ('status','extensions','session'):
            status,raw,_=self.req('/api/'+route);self.assertEqual(status,401);self.assertEqual(json.loads(raw),{'error':'UNAUTHORIZED'})
        self.assertEqual(self.backend.calls,[])
    def test_cookie_and_security_headers(self):
        h=self.login()
        for flag in ('Secure','HttpOnly','SameSite=Strict','Path=/','Max-Age=300'):self.assertIn(flag,h['Set-Cookie'])
        self.assertIn('frame-ancestors',h['Content-Security-Policy']);self.assertEqual(h['Cache-Control'],'no-store')
    def test_real_status_adapter(self):
        self.login();status,raw,_=self.req('/api/status');self.assertEqual(status,200);self.assertEqual(json.loads(raw)['data']['MainPID'],123)
    def test_management_health_and_authenticated_pause_resume(self):
        self.assertEqual(self.req('/api/management-health')[0],401)
        self.assertEqual(self.req('/api/management-recovery/pause',{})[0],401)
        self.login()
        status,raw,_=self.req('/api/management-health');self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['data']['overall'],'HEALTHY')
        status,raw,_=self.req('/api/management-recovery/pause',{});self.assertEqual(status,200)
        result=json.loads(raw);self.csrf=result['csrf'];self.assertEqual(result['data']['overall'],'PAUSED')
        status,raw,_=self.req('/api/management-recovery/resume',{});self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['data']['overall'],'HEALTHY')
        self.assertEqual(self.management.calls,
                         [('status',),('set_paused',True),('status',),('set_paused',False),('status',)])
    def test_origin_and_csrf_before_action(self):
        self.login()
        status,_,_=self.req('/api/preview',{}, {'Origin':'https://invalid.example'});self.assertEqual(status,401)
        status,_,_=self.req('/api/preview',{}, {'X-CSRF-Token':'wrong'});self.assertEqual(status,401);self.assertEqual(self.backend.calls,[])
    def test_profile_binding_requires_authenticated_write_and_is_in_browser_flow(self):
        self.assertEqual(self.req('/api/bind-extensions',{})[0],401)
        self.login()
        self.assertEqual(self.req('/api/bind-extensions',{}, {'Origin':'https://invalid.example'})[0],401)
        self.assertEqual(self.backend.calls,[])
        self.assertEqual(self.req('/api/bind-extensions',{})[0],200)
        self.assertEqual(len(self.backend.calls),1)
        self.assertEqual(self.req('/api/bind-extensions',{})[0],401)
        status,body,_=self.req('/app.js')
        self.assertEqual(status,200)
        self.assertIn(b"api('bind-extensions',{})",body)
    def test_replay_only_executes_once(self):
        self.login();status,_,_=self.req('/api/preview',{});self.assertEqual(status,200)
        status,raw,_=self.req('/api/preview',{});self.assertEqual(status,401);self.assertEqual(json.loads(raw)['error'],'CSRF_REJECTED');self.assertEqual(self.backend.calls,[('preview',)])
    def test_logout_revokes_access(self):
        self.login();status,_,h=self.req('/api/logout',{});self.assertEqual(status,200);self.assertIn('Max-Age=0',h['Set-Cookie'])
        self.assertEqual(self.req('/api/status')[0],401)
    def test_authority_revocation(self):
        self.login();self.authority.revoked=True;self.assertEqual(self.req('/api/status')[0],401);self.assertEqual(self.backend.calls,[])
    def test_no_arbitrary_commands_or_service(self):
        self.login();status,_,_=self.req('/api/start',{'bundleId':'1'*64,'service':'other.service'});self.assertEqual(status,401);self.assertEqual(self.backend.calls,[])
    def test_unknown_route_has_no_paths_or_internals(self):
        status,raw,_=self.req('/api/../../etc/passwd');self.assertEqual(status,401);self.assertNotIn(b'/etc',raw)
    def test_static_page_explains_split(self):
        status,body,_=self.req('/');self.assertEqual(status,200);self.assertIn('daed 原生 Run 不是独立 DAE 控制入口'.encode(),body)

    def test_referenced_empty_group_returns_authenticated_diagnostic(self):
        from bridge_m4.extensions import CompatibilityError
        def reject(token):raise CompatibilityError('EMPTY_REFERENCED_GROUP','groups.empty_fixture.nodes')
        self.backend.preview=reject
        self.assertEqual(self.req('/api/preview',{})[0],401)
        self.login();status,raw,_=self.req('/api/preview',{})
        self.assertEqual(status,409)
        self.assertEqual(json.loads(raw),{'error':'EMPTY_REFERENCED_GROUP','groupName':'empty_fixture','fieldPath':'groups.empty_fixture.nodes'})

    def test_binding_generation_conflict_is_explicit_and_fail_closed(self):
        from bridge_m4.extensions import CompatibilityError
        def reject(token):raise CompatibilityError('EXTENSION_CAS_CONFLICT','$')
        self.backend.bind_extensions=reject
        self.login();status,raw,_=self.req('/api/bind-extensions',{})
        self.assertEqual(status,409)
        self.assertEqual(json.loads(raw),{'error':'EXTENSION_CAS_CONFLICT'})
