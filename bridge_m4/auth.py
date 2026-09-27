"""Official daed administrator authentication and memory-only short sessions."""
import hashlib
import http.client
import json
import secrets
import threading
import time
from dataclasses import dataclass, field

class AuthError(Exception):
    pass

class DaedAuthenticator:
    def __init__(self, port=2024):
        if type(port) is not int or not 1<=port<=65535:raise AuthError('AUTH_CONFIGURATION')
        self.port=port
    def query(self, query, variables, token=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        try:
            headers={'Content-Type':'application/json'}
            if token:headers['Authorization']='Bearer '+token
            body=json.dumps({'query':query,'variables':variables}).encode()
            connection.request('POST','/graphql',body=body,headers=headers)
            response=connection.getresponse();raw=response.read(65537)
            if response.status!=200 or len(raw)>65536:raise AuthError('AUTH_FAILED')
            result=json.loads(raw)
            if not isinstance(result,dict) or result.get('errors') or not isinstance(result.get('data'),dict):raise AuthError('AUTH_FAILED')
            return result['data']
        except (OSError,ValueError,http.client.HTTPException):raise AuthError('AUTH_FAILED') from None
        finally:connection.close()
    def verify(self,token):
        if type(token) is not str or not 1<=len(token)<=8192 or any(c in token for c in '\r\n'):raise AuthError('AUTH_FAILED')
        data=self.query('query { configs { id } }',{},token)
        if not isinstance(data.get('configs'),list):raise AuthError('AUTH_FAILED')
    def login(self,credentials):
        if type(credentials) is not dict:raise AuthError('AUTH_FAILED')
        if set(credentials)=={'token'}:token=credentials['token']
        elif set(credentials)=={'username','password'}:
            if not all(type(v) is str and 1<=len(v)<=1024 for v in credentials.values()):raise AuthError('AUTH_FAILED')
            data=self.query('query($u:String!,$p:String!){token(username:$u,password:$p)}',{'u':credentials['username'],'p':credentials['password']})
            token=data.get('token')
        else:raise AuthError('AUTH_FAILED')
        self.verify(token);return token

def local_token(name):
    """Read one fixed root-owned secret; never treat a daed token as a login."""
    import os
    from bridge_m2.security import directory, read_at
    if name not in {'bridge-login.token','backend.token'}:raise AuthError('AUTH_CONFIGURATION')
    fd=directory('/etc/daed-independent-bridge',0,0,0o755)
    try:raw=read_at(fd,name,0,os.getegid(),0o640)
    finally:os.close(fd)
    value=raw.decode().strip()
    if not 32<=len(value)<=8192 or any(c.isspace() for c in value):raise AuthError('AUTH_CONFIGURATION')
    return value


class BridgeAuthenticator:
    """Separate bridge administrator credential, with no daed API dependency."""
    def __init__(self,reader=None):self.reader=reader or (lambda:local_token('bridge-login.token'))
    def verify(self,token):
        if type(token) is not str or not secrets.compare_digest(token.encode(),self.reader().encode()):
            raise AuthError('AUTH_FAILED')
    def login(self,credentials):
        if type(credentials) is not dict or set(credentials)!={'token'}:raise AuthError('AUTH_FAILED')
        token=credentials['token'];self.verify(token);return token


@dataclass
class Session:
    token:str = field(repr=False)
    csrf:str = field(repr=False)
    expires:float

class Sessions:
    def __init__(self, authenticator, now=time.monotonic, ttl=300):
        if type(ttl) is not int or not 1<=ttl<=900:raise AuthError('AUTH_CONFIGURATION')
        self.authenticator,self.now,self.ttl=authenticator,now,ttl
        self.sessions={};self.challenges={};self.attempts={};self.lock=threading.RLock()
    @staticmethod
    def key(value):
        if type(value) is not str or len(value)>8192:raise AuthError('UNAUTHORIZED')
        return hashlib.sha256(value.encode()).hexdigest()
    def prune(self):
        now=self.now()
        self.sessions={k:v for k,v in self.sessions.items() if v.expires>now}
        self.challenges={k:v for k,v in self.challenges.items() if v>now}
        self.attempts={k:v for k,v in self.attempts.items() if v[1]>now}
    def challenge(self):
        with self.lock:
            self.prune()
            if len(self.challenges)>=128:raise AuthError('AUTH_BUSY')
            token=secrets.token_urlsafe(32);self.challenges[self.key(token)]=self.now()+60
            return token
    def login(self,challenge,csrf,credentials,peer):
        with self.lock:
            self.prune();key=self.key(challenge)
            if type(csrf) is not str or not challenge or not secrets.compare_digest(challenge.encode(),csrf.encode()) or key not in self.challenges:raise AuthError('CSRF_REJECTED')
            del self.challenges[key]
            peer_key=self.key(peer);attempts,expires=self.attempts.get(peer_key,(0,self.now()+60))
            if attempts>=5 or len(self.attempts)>=1024:raise AuthError('AUTH_RATE_LIMIT')
            self.attempts[peer_key]=(attempts+1,expires)
            token=self.authenticator.login(credentials)
            if len(self.sessions)>=128:raise AuthError('AUTH_BUSY')
            sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
            self.sessions[self.key(sid)]=Session(token,csrf,self.now()+self.ttl)
            self.attempts.pop(peer_key,None)
            return sid,csrf
    def authorized(self,sid,csrf=None,mutating=False):
        with self.lock:
            self.prune();key=self.key(sid);session=self.sessions.get(key)
            if session is None:raise AuthError('UNAUTHORIZED')
            if mutating:
                if type(csrf) is not str or not secrets.compare_digest(session.csrf.encode(),csrf.encode()):raise AuthError('CSRF_REJECTED')
                session.csrf=secrets.token_urlsafe(32)  # consume before any work
            try:self.authenticator.verify(session.token)
            except AuthError:
                del self.sessions[key];raise AuthError('UNAUTHORIZED') from None
            return session.token,session.csrf
    def logout(self,sid):
        with self.lock:self.sessions.pop(self.key(sid),None)
