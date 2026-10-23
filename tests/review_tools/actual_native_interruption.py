"""Bounded destructive review tool. Only run inside an opted-in disposable INT VM.
Evidence path is fixed. Execute only this reviewed tree in the disposable guest.
"""
import os,fcntl,time,pathlib
if os.environ.get('BRIDGE_ISOLATED_NATIVE_REVIEW') != 'SIGKILL_INT_ONLY':
    raise RuntimeError('DISPOSABLE_NATIVE_REVIEW_REQUIRED')
import os,sys,pathlib,json,subprocess,time,hashlib,sqlite3,traceback,socketserver,threading
os.umask(0o077);sys.dont_write_bytecode=True
C=pathlib.Path(__file__).resolve().parents[2];E=pathlib.Path('/tmp/r6-completion-actual');E.mkdir(mode=0o700,exist_ok=True)
os.chdir(C);sys.path[:0]=[str(C),str(C/'out/m4-vendor'),'/tmp']
from tests.review_tools.ptrace_gate import trace,proc_identity
from tests.review_tools.injection_predicates import eligible, expected_from
from scripts import release_native_lifecycle as n
from scripts.m4_install import verify_installed
from bridge_m4.dns_sync_runtime import read_status
ENV=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(C/'out/m4-vendor'))
J=pathlib.Path('/var/lib/bridge-m4-install/native-lifecycle.json');T=J.with_name('transaction.json');M=pathlib.Path('/etc/daed-independent-bridge/install.json')
def save(name,v):
 p=E/name;data=v if isinstance(v,bytes) else (v if isinstance(v,str) else json.dumps(v,indent=2));mode='wb' if isinstance(data,bytes) else 'w'
 with p.open(mode) as f:f.write(data);f.flush();os.fsync(f.fileno())
 d=os.open(E,os.O_DIRECTORY);os.fsync(d);os.close(d)
def cmd(a,timeout=75):return subprocess.run(a,cwd=C,env=ENV,capture_output=True,text=True,timeout=timeout)
def show(units):
 r=cmd(['systemctl','show',*units,'--property=Id,LoadState,ActiveState,SubState,MainPID,ControlPID,InvocationID,NRestarts,UnitFileState,FragmentPath,DropInPaths']);
 if r.returncode:raise RuntimeError('SHOW_FAILED '+r.stderr)
 fields={}
 for block in r.stdout.strip().split('\n\n'):
  d=dict(l.split('=',1) for l in block.splitlines() if '=' in l);fields[d['Id']]=d
 return r.stdout,fields
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def files():
 roots=['/etc/daed-independent-bridge','/var/lib/bridge-daed','/var/lib/bridge-m4-client','/var/lib/bridge-m4-attestation','/var/lib/daed-independent-bridge','/opt/bridge-official/assets']
 return {str(p):{'sha256':sha(p),'mode':p.stat().st_mode&0o777,'uid':p.stat().st_uid,'gid':p.stat().st_gid} for r in roots for p in pathlib.Path(r).rglob('*') if p.is_file() and not p.is_symlink()}
def snap(name,status=True):
 raw,units=show(n.OWNED);save(name+'-units.log',raw)
 v={'time':time.time(),'native':json.loads(J.read_text()),'install':json.loads(T.read_text()),'manifest':sha(M),'files':files(),'units':units}
 for k,p in [('native',J),('install',T)]:save(name+'-'+k+'.json',p.read_bytes())
 control=pathlib.Path('/var/lib/bridge-m2/transaction.json')
 # Record actual policy state directory, not an assumed transaction path.
 from bridge_m4.authority import policy
 pol=policy();v['policyPaths']={k:str(getattr(pol,k)) for k in ('state','versions','inbox') if hasattr(pol,k)}
 for p in pathlib.Path('/var/lib').glob('bridge*/*transaction*'):
  if p.is_file():save(name+'-control-'+p.parent.name+'-'+p.name,p.read_bytes())
 if status:v['status'],v['expected']=read_status()
 db=sqlite3.connect('file:/var/lib/bridge-daed/wing.db?mode=ro',uri=True);v['integrity']=db.execute('pragma integrity_check').fetchone()[0];db.close()
 save(name+'.json',v);return v
# Reuse R6B synthetic upstream exactly; no public/production network.
def answer(data):
 end=12
 while data[end]:end+=1+data[end]
 end+=5
 return data[:2]+b'\x81\x80'+data[4:6]+b'\x00\x01\x00\x00\x00\x00'+data[12:end]+b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\xc0\x00\x02\x01'
class UDP(socketserver.BaseRequestHandler):
 def handle(self):data,s=self.request;s.sendto(answer(data),self.client_address)
class TCP(socketserver.BaseRequestHandler):
 def handle(self):
  h=self.request.recv(2)
  if len(h)!=2:return
  n=int.from_bytes(h,'big');data=b''
  while len(data)<n:
   x=self.request.recv(n-len(data))
   if not x:return
   data+=x
  ans=answer(data);self.request.sendall(len(ans).to_bytes(2,'big')+ans)
class TS(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
servers=[socketserver.ThreadingUDPServer(('127.0.0.1',5536),UDP),TS(('127.0.0.1',5536),TCP)]
for s in servers:threading.Thread(target=s.serve_forever,daemon=True).start()
results={}
try:
 for proto in ('udp','tcp'):
  r=cmd(['dig','@127.0.0.1','-p','5536','synthetic.test','A','+time=2','+tries=1']+(['+tcp'] if proto=='tcp' else []));save('fixture-'+proto+'.log',r.stdout+r.stderr)
  if r.returncode or '192.0.2.1' not in r.stdout:raise RuntimeError('FIXTURE_INVALID')
 verify_installed(json.loads(M.read_text()))
 r=cmd(['sh','health-check.sh'],180);save('baseline-health.log',r.stdout+r.stderr);results['baselineHealth']={'rc':r.returncode}
 if r.returncode:raise RuntimeError('BASELINE_HEALTH_FAILED')
 before=snap('before');expected=expected_from(before)
 observations=[]
 def observe(pid,ident,result):
  native=json.loads(J.read_text());install=json.loads(T.read_text());raw,timers=show(n.TIMERS)
  lockstat=pathlib.Path('/run/bridge-release.lock').stat();locks=pathlib.Path('/proc/locks').read_text()
  owned=any(' FLOCK ' in l and ' WRITE '+str(pid)+' ' in l and int(l.split()[5].rsplit(':',1)[1])==lockstat.st_ino for l in locks.splitlines())
  o={'time':time.time(),'native':native,'install':install,'manifest':sha(M),'timers':timers,'process':ident,'processMatches':ident['cwd']==str(C) and '-m scripts.release_lifecycle uninstall' in ident['argv'],'ownsReleaseLock':owned}
  ok,checks=eligible(o,expected);observations.append({'time':o['time'],'phase':native['phase'],'checks':checks})
  if not ok:return False
  save('pause-first.json',o);save('pause-timers-first.log',raw);save('pause-locks.log',locks)
  # At the same exact wait4 syscall stop, reread all raw state and identity before destructive signal.
  again=json.loads(J.read_text());raw2,timers2=show(n.TIMERS);identity2=proc_identity(pid)
  o2=dict(o,native=again,install=json.loads(T.read_text()),manifest=sha(M),timers=timers2,process=identity2,processMatches=identity2==ident)
  ok2,checks2=eligible(o2,expected)
  save('pause-second.json',dict(o2,checks=checks2));save('pause-timers-second.log',raw2)
  jr=cmd(['journalctl','--no-pager','-o','short-iso-precise','-n','120','-u',n.TIMERS[0],'-u',n.TIMERS[1],'-u','bridge-management-recovery.service','-u','dae.service','-u','daed-api.service']);save('pause-journal.log',jr.stdout+jr.stderr)
  if jr.returncode:raise RuntimeError('JOURNAL_CAPTURE_FAILED')
  save('pause-core.json',snap('pause',False));save('observations.json',observations)
  return ok2
 traced=trace(['sh','uninstall.sh'],str(C),str(E/'uninstall.log'),observe,timeout=180,env=ENV);results['interruption']=traced;save('trace-result.json',traced);save('observations.json',observations)
 if not traced['killSent'] or traced['exitCode']!=-9:raise RuntimeError('VALID_WINDOW_NOT_ESTABLISHED_NO_RETRY')
 killed=snap('killed',False)
 for name in ('recover','recover-second'):
  if name=='recover-second':
   # Observe a bounded idle lock window; do not retry the lifecycle command.
   deadline=time.monotonic()+60;lock_observations=[]
   with open('/run/bridge-release.lock','a') as probe:
    while True:
     try:
      fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(probe,fcntl.LOCK_UN);break
     except BlockingIOError:
      lock_observations.append({'time':time.time(),'locks':pathlib.Path('/proc/locks').read_text()})
      if time.monotonic()>=deadline:raise RuntimeError('SECOND_RECOVERY_LOCK_BUSY_NOT_EXECUTED')
      time.sleep(.2)
   save('second-recovery-lock-window.json',lock_observations)
  start=time.time();r=cmd(['sh','install.sh','--recover-native'],180);save(name+'.log',r.stdout+r.stderr);results[name]={'command':['sh','install.sh','--recover-native'],'cwd':str(C),'rc':r.returncode,'seconds':time.time()-start};save('results.json',results)
  if name=='recover' and r.returncode:raise RuntimeError('RECOVER_FAILED')
  if name=='recover-second' and (r.returncode==0 or 'NATIVE_NO_PENDING_RECOVERY' not in r.stdout+r.stderr):raise RuntimeError('SECOND_RECOVERY_WRONG_CONTRACT')
  snap(name+'-after')
 after=snap('after');important=['/var/lib/bridge-daed/wing.db','/etc/daed-independent-bridge/bridge-login.token','/etc/daed-independent-bridge/attestor.token','/etc/daed-independent-bridge/tls.crt','/etc/daed-independent-bridge/tls.key']
 checks={'manifestUnchanged':before['manifest']==after['manifest'],'generationUnchanged':before['install']['generation']==after['install']['generation'],'RESTORED':after['native']['phase']=='RESTORED','coreIdentityUnchanged':all(all(before['units'][u][k]==after['units'][u][k] for k in ('MainPID','InvocationID','NRestarts')) for u in ('dae.service','daed-api.service')),'bundleUnchanged':before['status']['activeBundle']==after['status']['activeBundle'],'configUnchanged':before['status']['configSha256']==after['status']['configSha256'],'datUnchanged':all(before['files'][p]==after['files'][p] for p in before['files'] if p.startswith('/opt/bridge-official/assets/')),'persistentBytesUnchanged':all(before['files'][p]==after['files'][p] for p in important),'timerIntentRestored':all(before['units'][u]['ActiveState']==after['units'][u]['ActiveState'] for u in n.TIMERS)}
 results['checks']=checks
 if not all(checks.values()):raise RuntimeError('POST_RECOVERY_IDENTITY_DRIFT')
 r=cmd(['sh','health-check.sh'],180);save('after-health.log',r.stdout+r.stderr);results['afterHealth']={'rc':r.returncode}
 if r.returncode:raise RuntimeError('AFTER_HEALTH_FAILED')
 results['result']='PASS'
except BaseException as exc:
 save('failure.traceback.txt',traceback.format_exc());results['result']='STOPPED';results['exception']=type(exc).__name__;results['message']=str(exc)
finally:
 save('results.json',results)
 for s in servers:s.shutdown();s.server_close()
 print(json.dumps(results,indent=2))
