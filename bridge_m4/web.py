"""TLS-only authenticated management surface; fixed route/action dispatch."""
import json
import os
import ssl
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .auth import AuthError, BridgeAuthenticator, Sessions, local_token
from bridge_m2.security import Denied,check
from .runtime import Runtime

STATIC=Path(__file__).with_name('web')
COOKIE='__Host-bridge'
CHALLENGE='__Host-bridge-login'

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,origin,sessions,runtime):
        self.origin,self.sessions,self.runtime=origin,sessions,runtime
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    server_version='Bridge'
    sys_version=''
    def log_message(self,*args):pass
    def setup(self):
        super().setup();self.connection.settimeout(10)
    def reply(self,status,value,*,cookie=None,content_type='application/json'):
        data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('Strict-Transport-Security','max-age=31536000')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(data)
    @staticmethod
    def cookie(name,value,age):return f'{name}={value}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={age}'
    def cookies(self):
        jar=SimpleCookie()
        try:jar.load(self.headers.get('Cookie',''))
        except Exception:raise AuthError('UNAUTHORIZED') from None
        return {k:v.value for k,v in jar.items()}
    def body(self):
        if self.headers.get('Content-Type')!='application/json' or self.headers.get('Transfer-Encoding') is not None:raise AuthError('REQUEST_REJECTED')
        try:length=int(self.headers.get('Content-Length','-1'))
        except ValueError:raise AuthError('REQUEST_REJECTED') from None
        if not 0<length<=16384:raise AuthError('REQUEST_REJECTED')
        raw=self.rfile.read(length)
        if len(raw)!=length:raise AuthError('REQUEST_REJECTED')
        try:
            def unique(pairs):
                out={}
                for k,v in pairs:
                    if k in out:raise ValueError()
                    out[k]=v
                return out
            value=json.loads(raw,object_pairs_hook=unique)
        except (ValueError,UnicodeError):raise AuthError('REQUEST_REJECTED') from None
        if type(value) is not dict:raise AuthError('REQUEST_REJECTED')
        return value
    def dispatch(self,mutating):
        route=urlsplit(self.path)
        if route.query or route.fragment:raise AuthError('REQUEST_REJECTED')
        path=route.path
        if self.headers.get('Host')!=urlsplit(self.server.origin).netloc:raise AuthError('REQUEST_REJECTED')
        if not mutating and path in {'/','/app.js','/style.css'}:
            name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[path]
            self.reply(200,(STATIC/name).read_bytes(),content_type={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[path]);return
        if not mutating and path=='/api/challenge':
            c=self.server.sessions.challenge()
            self.reply(200,{'csrf':c},cookie=self.cookie(CHALLENGE,c,60));return
        cookies=self.cookies()
        if mutating and self.headers.get('Origin')!=self.server.origin:raise AuthError('CSRF_REJECTED')
        if mutating and path=='/api/login':
            value=self.body()
            sid,csrf=self.server.sessions.login(cookies.get(CHALLENGE,''),self.headers.get('X-CSRF-Token',''),value,self.client_address[0])
            self.reply(200,{'csrf':csrf},cookie=self.cookie(COOKIE,sid,self.server.sessions.ttl));return
        sid=cookies.get(COOKIE,'')
        token,csrf=self.server.sessions.authorized(sid,self.headers.get('X-CSRF-Token'),mutating)
        if not mutating:
            if path=='/api/session':value={}
            elif path=='/api/status':value=self.server.runtime.action('status')
            elif path=='/api/extensions':
                value=({'setupRequired':True,'generation':None,'records':{}} if not Path('/etc/daed-independent-bridge/backend.token').exists() else self.server.runtime.extensions())
            else:raise AuthError('REQUEST_REJECTED')
        else:
            value=self.body()
            if path=='/api/logout':
                if value:raise AuthError('REQUEST_REJECTED')
                self.server.sessions.logout(sid)
                self.reply(200,{'loggedOut':True},cookie=self.cookie(COOKIE,'',0));return
            elif path=='/api/preview' and not value:value=self.server.runtime.preview(token)
            elif path=='/api/bind-extensions' and not value:value=self.server.runtime.bind_extensions(token)
            elif path=='/api/extensions':value=self.server.runtime.edit(value)
            elif path in {'/api/validate','/api/apply'} and set(value)=={'previewId'}:
                value=self.server.runtime.validate(value['previewId']) if path.endswith('validate') else self.server.runtime.apply(token,value['previewId'])
            elif path in {'/api/start','/api/stop','/api/reload','/api/recover'} and set(value)=={'bundleId'}:
                value=self.server.runtime.action(path[5:],value['bundleId'])
            else:raise AuthError('REQUEST_REJECTED')
        self.reply(200,{'csrf':csrf,'data':value})
    def run_request(self,mutating):
        try:self.dispatch(mutating)
        except (BrokenPipeError,ConnectionResetError):
            # A disconnected client cannot receive another HTTP response.
            self.close_connection=True
        except AuthError as exc:
            code=str(exc) if str(exc) in {'UNAUTHORIZED','AUTH_FAILED','CSRF_REJECTED','AUTH_RATE_LIMIT','AUTH_BUSY','REQUEST_REJECTED'} else 'AUTH_FAILED'
            self.reply(429 if code in {'AUTH_RATE_LIMIT','AUTH_BUSY'} else 401,{'error':code})
        except Exception as exc:
            from .diagnostics import failure
            failure("web",exc)
            from .extensions import empty_group_diagnostic
            diagnostic=empty_group_diagnostic(exc)
            if diagnostic is not None:
                self.reply(409,diagnostic)
                return
            # Domain codes contain no source values; upstream messages never reach clients.
            allowed={'SOURCE_CHANGED','EXTENSION_CHANGED','PREVIEW_CONFLICT','EXTENSION_CAS_CONFLICT','VALIDATION_REQUIRED','VALIDATE_FAILED','OLD_SOURCE','SOURCE_EXPIRED','STATUS_REJECTED','UNMANAGED_SERVICE_ACTIVE','MANUAL_INTERVENTION_REQUIRED','UNIT_IDENTITY_MISMATCH'}
            from .extensions import CompatibilityError
            code=(exc.code if isinstance(exc,CompatibilityError) and exc.code=='EXTENSION_CAS_CONFLICT'
                  else str(exc) if isinstance(exc,Denied) and str(exc) in allowed else 'REQUEST_FAILED')
            self.reply(409,{'error':code})
    def do_GET(self):self.run_request(False)
    def do_POST(self):self.run_request(True)

def main():
    check(os.geteuid()!=0,'BRIDGE_MUST_NOT_BE_ROOT')
    from .authority import manifest
    manifest()
    from bridge_m2.security import directory,read_at,load_json
    fd=directory('/etc/daed-independent-bridge',0,0,0o755)
    try:config=load_json(read_at(fd,'web.json',0,os.getegid(),0o640))
    finally:os.close(fd)
    check(set(config)=={'address','port','origin'},'WEB_CONFIGURATION')
    import ipaddress
    ipaddress.IPv4Address(config['address'])
    check(type(config['port']) is int and 1024<=config['port']<=65535,'WEB_CONFIGURATION')
    origin=urlsplit(config['origin'])
    check(origin.scheme=='https' and origin.hostname==config['address'] and origin.port==config['port'] and not origin.path and not origin.query and not origin.fragment and not origin.username,'WEB_CONFIGURATION')
    from .collect import collect
    from bridge_m1.collect import HTTPReader
    from .runtime import ENDPOINT
    # Session tokens authorize this Web only. Never forward them to daed.
    runtime=Runtime(collector=lambda _session_token:collect(HTTPReader(ENDPOINT,local_token('backend.token'))))
    server=Server((config['address'],config['port']),config['origin'],Sessions(BridgeAuthenticator()),runtime)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain('/etc/daed-independent-bridge/tls.crt','/etc/daed-independent-bridge/tls.key')
    server.socket=context.wrap_socket(server.socket,server_side=True)
    server.serve_forever()

if __name__=='__main__':main()
