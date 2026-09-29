#!/usr/bin/python3
"""Synchronize only applied business DNS rules; retain last good on any error."""
from pathlib import Path
import hashlib,subprocess,os,tempfile,json,fcntl,time,shutil,ipaddress
from urllib.parse import urlsplit

def identity_action(previous, fingerprint, bundle_id, config_sha256):
 if previous.get('fingerprint') != fingerprint:return 'full'
 if previous.get('activeBundle') != bundle_id or previous.get('configSha256') != config_sha256:
  return 'refresh'
 return 'unchanged'

def refresh_identity_atomically(statefile, previous, bundle_id, config_sha256):
 refreshed=dict(previous)
 refreshed.update(source='INDEPENDENT_BRIDGE',activeBundle=bundle_id,
                  configSha256=config_sha256,verified_at=time.time())
 fd,name=tempfile.mkstemp(prefix='.independent-sync-',dir=statefile.parent)
 try:
  with os.fdopen(fd,'w') as stream:
   os.fchmod(stream.fileno(),0o600)
   json.dump(refreshed,stream,separators=(',',':'))
   stream.flush();os.fsync(stream.fileno())
  os.replace(name,statefile)
  directory=os.open(statefile.parent,os.O_RDONLY)
  try:os.fsync(directory)
  finally:os.close(directory)
 finally:
  if os.path.exists(name):os.unlink(name)

def reconcile_identity(previous, fingerprint, bundle_id, config_sha256, statefile, read_status):
 action=identity_action(previous,fingerprint,bundle_id,config_sha256)
 if action=='full':return False
 if action=='refresh':
  again,again_expected=read_status()
  if (again.get('state')!='running' or again.get('identityVerified') is not True or
      again.get('activeBundle')!=bundle_id or again.get('configSha256')!=config_sha256 or
      again_expected!=config_sha256):
   raise SystemExit('Independent source changed; policy retained')
  refresh_identity_atomically(statefile,previous,bundle_id,config_sha256)
  print('POLICY_SYNC_SOURCE=INDEPENDENT_BRIDGE IDENTITY_REFRESHED=true RELOAD=false')
 return True

ROOT=Path('/etc/dae-dns-repair');STATE=Path('/var/lib/dae-dns-repair');STATE.mkdir(exist_ok=True)
INGRESS=Path('/var/lib/dae-ingress-sync/state.json')
lock=open('/run/independent-policy-sync.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
import sys,re
sys.path[:0]=['/opt/bridge','/opt/bridge/vendor']
from bridge_m4.dns_sync_runtime import read_status
status,expected=read_status()
if status.get('state')!='running' or status.get('identityVerified') is not True or status.get('configSha256')!=expected:
 raise SystemExit('Independent DAE identity unavailable; policy retained')
identity=status['activeBundle']
if not re.fullmatch('[0-9a-f]{64}',identity):raise SystemExit('Invalid bundle identity')
bundle=Path('/var/lib/daed-independent-bridge/versions')/identity
ir=json.loads((bundle/'normalized-ir.json').read_text())
route=''.join(t['text'] for t in ir['routing']['tokens'])
geo=Path('/usr/share/daed/geosite.dat');gen=ROOT/'build_dns.py'
ingress=json.loads(INGRESS.read_text())
if ingress.get('version')!=1 or not isinstance(ingress.get('mappings'),dict) or not ingress['mappings']:
 raise SystemExit('Invalid ingress-sync state; DNS policy retained')
mapping_hosts={str(host).lower().rstrip('.') for host in ingress['mappings']}
mapping_view=[]
for host,m in sorted(ingress['mappings'].items()):
 address=m.get('last_known_good') if m.get('enabled') is True else None
 if address:address=str(ipaddress.IPv4Address(address))
 mapping_view.append((str(host).lower().rstrip('.'),address))
# Refuse a policy refresh if a fixed production node has no maintained ingress
# mapping: otherwise the node's hostname would silently fall back to public DNS.
endpoint_hosts=set()
for node in ir['nodes']:
 if not node['active']:continue
 host=urlsplit(node['link']).hostname
 if not host:
  raise SystemExit('Cannot identify a fixed node endpoint hostname; DNS policy retained')
 try:ipaddress.ip_address(host);raise SystemExit('Fixed node uses an IP literal without an optimized mapping; DNS policy retained')
 except ValueError:pass
 endpoint_hosts.add(host.lower().rstrip('.'))
missing=endpoint_hosts-mapping_hosts
if missing:raise SystemExit('A fixed node endpoint lacks an ingress mapping; DNS policy retained')
ingress_view=json.dumps({'mappings':mapping_view,'endpoints':sorted(endpoint_hosts)},sort_keys=True,separators=(',',':')).encode()
fingerprint=hashlib.sha256(route.encode()+geo.read_bytes()+gen.read_bytes()+ingress_view).hexdigest()
statefile=STATE/'independent-sync.json'
oldstate=json.loads(statefile.read_text()) if statefile.exists() else {}
if reconcile_identity(oldstate,fingerprint,identity,expected,statefile,read_status):raise SystemExit(0)
stage=Path(tempfile.mkdtemp(prefix='generation-',dir=ROOT));(stage/'routing.txt').write_text(route)
env=dict(os.environ,DNS_OUTPUT_DIR=str(stage),DNS_ROUTING_FILE=str(stage/'routing.txt'),DNS_GEOSITE_FILE=str(geo),DNS_DATA_DIR=str(stage),DNS_INGRESS_STATE_FILE=str(INGRESS))
subprocess.run(['/usr/bin/python3',str(gen)],env=env,check=True,capture_output=True)
subprocess.run(['/usr/bin/dnsdist','--check-config','-C',str(stage/'policy-dns.conf')],check=True,capture_output=True)
config=ROOT/'policy-dns.conf';old=config.read_bytes();new=(stage/'policy-dns.conf').read_bytes()

# Paths differ across immutable generations; compare referenced data as well.
def equivalent_current():
 text=old.decode();candidate=new.decode()
 for name in ('cn-suffix.txt','cn-full.txt'):
  match=re.search(r'io.lines\("([^"\n]+/'+re.escape(name)+r')"\)',text)
  if not match or Path(match.group(1)).read_bytes()!=(stage/name).read_bytes():return False
  text=text.replace(match.group(1),'@DATA@/'+name)
  candidate=candidate.replace(str(stage/name),'@DATA@/'+name)
 return text==candidate
again,again_expected=read_status()
if again.get('activeBundle')!=identity or again.get('configSha256')!=expected or again.get('identityVerified') is not True:
 shutil.rmtree(stage);raise SystemExit('Independent source changed; policy retained')
if equivalent_current():
 statefile.write_text(json.dumps(dict(fingerprint=fingerprint,source='INDEPENDENT_BRIDGE',activeBundle=identity,configSha256=expected,verified_at=time.time())))
 shutil.rmtree(stage)
 print('POLICY_SYNC_SOURCE=INDEPENDENT_BRIDGE CURRENT_POLICY_IDENTICAL=true RELOAD=false')
 raise SystemExit(0)
if '--verify-current' in sys.argv:
 shutil.rmtree(stage);raise SystemExit('CURRENT_POLICY_DIFFERENCE; no policy changed')
def install(b):
 p=ROOT/'policy-dns.conf.next';p.write_bytes(b);p.chmod(0o644);p.replace(config)
def probe(name,kind,expect):
 out=subprocess.run(['dig','@127.0.0.1','-p','5534',name,kind,'+tcp','+time=3','+tries=1'],capture_output=True,text=True,timeout=5)
 return out.returncode==0 and 'status: '+expect+',' in out.stdout
def probe_ingress(name,kind,expected=None,tcp=False):
 args=['dig','@127.0.0.1','-p','5534',name,kind,'+noall','+comments','+answer','+authority','+time=3','+tries=1']
 if tcp:args.append('+tcp')
 out=subprocess.run(args,capture_output=True,text=True,timeout=5)
 if out.returncode or 'status: NOERROR,' not in out.stdout:return False
 answers=[line.split() for line in out.stdout.splitlines() if '\tIN\t' in line or ' IN ' in line]
 if kind=='A':return any(len(row)>=5 and row[-2]=='A' and row[-1]==expected and row[1]=='5' for row in answers)
 return not any(len(row)>=5 and row[-2]==kind for row in answers) and any(' SOA ' in line for line in out.stdout.splitlines())
try:
 install(new);subprocess.run(['systemctl','restart','dae-policy-dns'],check=True)
 ok=False
 for _ in range(5):
  time.sleep(1)
  if probe('www.baidu.com','A','NOERROR') and probe('chatgpt.com','A','NOERROR') and probe('invalid.invalid','A','NXDOMAIN'):ok=True;break
 if not ok:raise RuntimeError('New policy failed runtime probes')
 for host,m in ingress['mappings'].items():
  address=m.get('last_known_good') if m.get('enabled') is True else None
  if not address:raise RuntimeError('Ingress mapping has no enabled LKG; policy must remain fail-closed')
  address=str(ipaddress.IPv4Address(address))
  for kind in ('A','AAAA','HTTPS','SVCB'):
   for tcp in (False,True):
    if not probe_ingress(host,kind,address if kind=='A' else None,tcp):
     raise RuntimeError('New policy failed ingress mapping DNS probe')
except Exception:
 install(old);subprocess.run(['systemctl','restart','dae-policy-dns'],check=True);raise
statefile.write_text(json.dumps(dict(fingerprint=fingerprint,source="INDEPENDENT_BRIDGE",activeBundle=identity,configSha256=expected,generation=str(stage),applied_at=time.time()),indent=2))
print('Applied independent DNS policy',identity,'with',len(ingress['mappings']),'optimized ingress mappings')
