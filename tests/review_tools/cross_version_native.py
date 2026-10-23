"""One bounded real R5 -> candidate upgrade/failure-rollback in a disposable VM.

No product substitution: invokes the two actual reviewed shell entrypoints. The
only fault is a temporary loopback listener preventing the candidate API bind.
Never import this module as a normal regression test.
"""
import os
if os.environ.get('BRIDGE_ISOLATED_NATIVE_REVIEW') != 'CROSS_VERSION_INT_ONLY':
    raise RuntimeError('DISPOSABLE_NATIVE_REVIEW_REQUIRED')
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import socket
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
import traceback

NEW = Path(__file__).resolve().parents[2]
OLD = Path('/tmp/reviewed-r5')
parser=argparse.ArgumentParser()
parser.add_argument('--reuse-restored-r5',type=Path)
args=parser.parse_args()
E = Path('/var/tmp/r6-cross-version')
E.mkdir(mode=0o700, exist_ok=False)
sys.path[:0] = [str(NEW), '/opt/bridge/vendor']
from tests.review_tools.ptrace_gate import trace
from integration.packaging.cross_version import verify_pair
from scripts import release_native_lifecycle as native
from bridge_m4.dns_sync_runtime import read_status

os.umask(0o077)
J = Path('/var/lib/bridge-m4-install/native-lifecycle.json')
M = Path('/etc/daed-independent-bridge/install.json')

def need(ok, code):
    if not ok: raise RuntimeError(code)

def save(name, value):
    body = value if isinstance(value, bytes) else (json.dumps(value, indent=2)+'\n').encode()
    with (E/name).open('xb') as f:
        f.write(body); f.flush(); os.fsync(f.fileno())

def command(args, source=NEW, timeout=360):
    return subprocess.run(args, cwd=source, capture_output=True, timeout=timeout,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(source/'out/m4-vendor')))

def idle_lock():
    # A read-only wait for a bounded idle slot, never retry a lifecycle command.
    until = time.monotonic()+60
    with open('/run/bridge-release.lock', 'a') as f:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN); return
            except BlockingIOError:
                need(time.monotonic()<until, 'RELEASE_LOCK_BUSY_NO_COMMAND_EXECUTED')
                time.sleep(.2)

def step(name, args, source=NEW):
    idle_lock(); started=time.time(); result=command(args, source)
    save(name+'.stdout', result.stdout); save(name+'.stderr', result.stderr)
    save(name+'.json', {'argv':args, 'source':str(source), 'exitCode':result.returncode,
        'startedAt':started, 'endedAt':time.time(), 'optimize':sys.flags.optimize})
    need(result.returncode==0, 'CROSS_VERSION_FAILED:'+name)
    return result

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def snapshot(name):
    units=command(['systemctl','show',*native.OWNED,
        '--property=Id,LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts,UnitFileState'])
    need(units.returncode==0, 'SYSTEMD_SHOW_FAILED')
    save(name+'-units.log', units.stdout)
    paths=[Path('/var/lib/bridge-daed/wing.db')]
    for root in ('/etc/daed-independent-bridge','/var/lib/bridge-m4-client/extensions',
                 '/opt/bridge-official/assets'):
        paths += [p for p in Path(root).rglob('*') if p.is_file() and not p.is_symlink()]
    # install identity is separately checked; generated receipts/status are not
    # immutable application data and are intentionally not in this comparison.
    paths=[p for p in paths if p.name not in {'install.json'}]
    files={str(p):{'sha256':digest(p),'mode':p.stat().st_mode&0o777,
                    'uid':p.stat().st_uid,'gid':p.stat().st_gid} for p in paths}
    db=sqlite3.connect('file:/var/lib/bridge-daed/wing.db?mode=ro',uri=True)
    integrity=db.execute('pragma integrity_check').fetchone()[0];db.close()
    state,expected=read_status()
    result={'files':files,'manifest':digest(M), 'integrity':integrity,
        'status':state,'expectedConfig':expected,
        'native':json.loads(J.read_text()),
        'official':{str(p):digest(p) for p in map(Path,
            ['/opt/bridge-official/dae','/opt/bridge-official/daed','/opt/bridge-service/dae'])}}
    save(name+'.json',result); return result

def equivalent(before, after):
    return {'persistentFiles':before['files']==after['files'],
        'databaseIntegrity':after['integrity']=='ok',
        'bundle':before['status']['activeBundle']==after['status']['activeBundle'],
        'configuration':before['status']['configSha256']==after['status']['configSha256']==after['expectedConfig'],
        'runningIdentity':after['status']['state']=='running' and after['status']['identityVerified'] is True,
        'officialFiles':before['official']==after['official']}

# The same no-network synthetic DNS upstream used for R6B authorization/health.
def answer(data):
    end=12
    while data[end]:end+=1+data[end]
    end+=5
    return data[:2]+b'\x81\x80'+data[4:6]+b'\x00\x01\x00\x00\x00\x00'+data[12:end]+b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\xc0\x00\x02\x01'
class UDP(socketserver.BaseRequestHandler):
    def handle(self):data,s=self.request;s.sendto(answer(data),self.client_address)
class TCP(socketserver.BaseRequestHandler):
    def handle(self):
        head=self.request.recv(2)
        if len(head)!=2:return
        size=int.from_bytes(head,'big');data=b''
        while len(data)<size:
            more=self.request.recv(size-len(data))
            if not more:return
            data+=more
        value=answer(data);self.request.sendall(len(value).to_bytes(2,'big')+value)
class TS(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
servers=[];fault={};listener=None;watcher=None
try:
    need(Path('/run/systemd/system').is_dir() and os.geteuid()==0, 'SYSTEMD_GUEST_REQUIRED')
    # The host forwards only this guest's SSH; it blocks outbound network. This
    # fixed marker is installed by the controller, never inferred from a label.
    need(Path('/run/review-r6-isolation').read_text().strip()=='QEMU_USER_RESTRICT_ON_18244',
         'ISOLATION_MARKER_REQUIRED')
    save('source-pair.json',verify_pair(OLD,NEW))
    servers=[socketserver.ThreadingUDPServer(('127.0.0.1',5536),UDP),TS(('127.0.0.1',5536),TCP)]
    for server in servers:threading.Thread(target=server.serve_forever,daemon=True).start()
    if args.reuse_restored_r5 is None:
        step('initial-health',['sh','health-check.sh'])
        initial=snapshot('initial')
        step('retaining-uninstall',['sh','uninstall.sh'])
        step('r5-retained-install',['sh','install.sh'],OLD)
        step('r5-health',['sh','health-check.sh'],OLD)
        old=snapshot('r5-before-fault')
        need(all(equivalent(initial,old).values()), 'R5_BASELINE_DATA_DRIFT')
    else:
        previous=args.reuse_restored_r5.resolve(strict=True)
        need(previous.parent==E.parent and previous!=E,'REUSE_EVIDENCE_PATH')
        priorfile=previous/'r5-before-fault.json'
        old=json.loads(priorfile.read_text())
        step('reused-r5-health',['sh','health-check.sh'],OLD)
        current=snapshot('reused-r5-current')
        need(all(equivalent(old,current).values()) and old['manifest']==current['manifest']
             and current['native']['phase']=='RESTORED','REUSED_R5_IDENTITY_MISMATCH')
        save('reused-baseline.json',{'source':str(priorfile),'sha256':digest(priorfile),
             'verifiedManifest':current['manifest'],'scope':'reuse actual retained R5 install; recheck live state'})
    prior=old['native']['attemptId']
    def stop_fault_on_failure():
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            r=command(['systemctl','show','daed-api.service',
                '--property=ActiveState,Result,ExecMainStatus,InvocationID'])
            fields=dict(l.split('=',1) for l in r.stdout.decode().splitlines() if '=' in l)
            if fields.get('Result')=='exit-code' and fields.get('ActiveState') in {'failed','activating'}:
                fault.setdefault('observedFailure',fields)
            transaction=json.loads(Path('/var/lib/bridge-m4-install/transaction.json').read_text())
            if transaction.get('context')=={'kind':'native-lifecycle','attemptId':fault['journal']['attemptId']} and transaction['phase'] in {'RESTORING','RESTORED'}:
                fault['restorePhase']=transaction['phase'];fault['closedAt']=time.time()
                listener.close();return
            time.sleep(.05)
        fault['watcherFailure']='API_FAILURE_NOT_OBSERVED'
        listener.close()
    def inject(pid, identity, result):
        global listener,watcher
        j=json.loads(J.read_text())
        if fault or j['phase']!='STARTING' or j['attemptId']==prior:return False
        need(identity['cwd']==str(NEW) and '-m scripts.release_lifecycle upgrade' in identity['argv'],
             'FAULT_WRONG_PROCESS')
        r=command(['systemctl','show','daed-api.service','--property=MainPID,ActiveState'])
        need(b'MainPID=0' in r.stdout and b'ActiveState=inactive' in r.stdout,'OLD_API_NOT_STOPPED')
        listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind(('127.0.0.1',2024));listener.listen(1)
        fault.update(injectedAt=time.time(),journal=j,process=identity,kind='loopback API bind conflict')
        watcher=threading.Thread(target=stop_fault_on_failure);watcher.start()
        save('injected-fault.json',fault)
        return 'observe-completion'  # detach after the exact injection, retain child exit status
    idle_lock()
    result=trace(['sh','upgrade.sh'],str(NEW),E/'upgrade-injected.log',inject,
        timeout=420,env={'PYTHONPATH':str(NEW/'out/m4-vendor'),'PYTHONDONTWRITEBYTECODE':'1'})
    if watcher:watcher.join(timeout=95)
    save('fault-outcome.json',fault);save('fault-trace.json',result)
    journal=command(['journalctl','--no-pager','-n','150','-u','daed-api.service','-u','dae.service'])
    save('fault-journal.log',journal.stdout+journal.stderr)
    need(fault.get('observedFailure') and not fault.get('watcherFailure'),'FAULT_INJECTION_NOT_PROVED')
    need(result['exitCode']!=0,'FAILED_UPGRADE_MUST_NOT_RETURN_SUCCESS')
    restored=snapshot('r5-restored')
    checks=equivalent(old,restored)
    checks.update(manifestRestored=old['manifest']==restored['manifest'],
                  transactionRestored=restored['native']['phase']=='RESTORED')
    save('rollback-checks.json',checks)
    need(all(checks.values()),'CROSS_VERSION_ROLLBACK_INCOMPLETE')
    step('rollback-health',['sh','health-check.sh'],OLD)
    step('new-upgrade',['sh','upgrade.sh'])
    step('new-health',['sh','health-check.sh'])
    final=snapshot('new-final');checks=equivalent(old,final)
    # Verify the installed manifest itself and its exact candidate payload.
    from scripts.m4_install import verify_installed,payload
    record=json.loads(M.read_text());verify_installed(record)
    expected=payload(release_profile=True,native_dns=True)
    checks['exactCandidateManifest']=set(expected)==set(record['files']) and all(
        hashlib.sha256(body).hexdigest()==record['files'][name]['sha256'] for name,(body,mode) in expected.items())
    save('upgrade-checks.json',checks)
    need(all(checks.values()),'CROSS_VERSION_UPGRADE_IDENTITY')
    save('result.json',{'passed':True,'rollback':True,'normalUpgrade':True,
        'scope':'reviewed R5 to this candidate, native DNS; no production; no version generalization'})
except BaseException as exc:
    save('failure.json',{'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()})
    raise
finally:
    if listener:listener.close()
    for server in servers:server.shutdown();server.server_close()
