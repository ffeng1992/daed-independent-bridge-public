"""Fixed-service systemd adapter and crash-recoverable publisher."""
import fcntl
import os
from pathlib import Path
import re
import subprocess
import time
from .bundle import FILES, verify_bundle
from .unit_identity import verify as verify_unit
from .security import check, Denied, atomic_json, canonical, digest, load_json, read_at, read_set, directory, syncdir, write_file

BASE = Path('/var/lib/daed-independent-bridge')
HEX = re.compile(r'[0-9a-f]{64}')
ACTIONS = {'apply','status','recover','start','stop','reload'}
ENV = {'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','LC_ALL':'C'}


def request(raw):
    value = load_json(raw)
    check(isinstance(value,dict) and value.get('action') in ACTIONS and set(value)<= {'action','bundleId'}, 'REQUEST_REJECTED')
    check(value['action']=='status' or 'bundleId' in value,'BUNDLE_ID')
    if 'bundleId' in value:check(isinstance(value['bundleId'],str) and HEX.fullmatch(value['bundleId']) is not None, 'BUNDLE_ID')
    return value


class Systemd:
    def __init__(self, policy):self.policy=policy

    def verify_unit(self):return verify_unit(self.policy,ENV)

    def command(self, action):
        check(action in {'start','stop','reload','reset-failed'}, 'ACTION_REJECTED')
        self.verify_unit()
        r = subprocess.run(['/usr/bin/systemctl',action,'dae.service'],env=ENV,capture_output=True,timeout=15)
        check(r.returncode == 0,'SERVICE_'+action.upper()+'_FAILED')

    def observe(self, candidate=None):
        r = subprocess.run(['/usr/bin/systemctl','show','dae.service','--no-pager','--property=ActiveState,SubState,MainPID,InvocationID'],env=ENV,capture_output=True,timeout=5)
        check(r.returncode==0,'SYSTEMD_UNAVAILABLE')
        raw=dict(line.split('=',1) for line in r.stdout.decode().splitlines() if '=' in line)
        pid=int(raw['MainPID']);state={'inactive':'stopped','activating':'starting','active':'running','reloading':'reloading','deactivating':'rollback-needed','failed':'failed'}.get(raw['ActiveState'],'failed')
        if state=='stopped' and pid!=0:state='rollback-needed'
        result={'state':state,'systemd':raw,'identityVerified':False}
        if state=='running':
            try:
                check(pid>0 and bool(re.fullmatch('[0-9a-f]{32}',raw['InvocationID'])),'PROCESS_ID')
                before=Path(f'/proc/{pid}/stat').read_text()
                exe=digest(Path(f'/proc/{pid}/exe').read_bytes())
                argv=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[:-1]
                check(candidate is not None and argv[1:]==[b'run',b'-c',os.fsencode(candidate)],'PROCESS_CONFIG')
                config=digest(candidate.read_bytes())
                check(exe==self.policy['serviceBinarySha256'],'PROCESS_BINARY')
                again=subprocess.run(['/usr/bin/systemctl','show','dae.service','--property=MainPID,InvocationID'],env=ENV,capture_output=True,timeout=5)
                fields=dict(line.split('=',1) for line in again.stdout.decode().splitlines() if '=' in line)
                check(fields=={k:raw[k] for k in ('MainPID','InvocationID')} and Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()[19]==before.split(') ',1)[1].split()[19], 'PROCESS_CHANGED')
                result.update(identityVerified=True,executableSha256=exe,configSha256=config)
            except (OSError,Denied,ValueError):result['state']='rollback-needed'
        return result

    def healthy(self, candidate, expected):
        first=None;stable=0
        for _ in range(40):
            result=self.observe(candidate)
            valid=result['state']=='running' and result['identityVerified'] and result['configSha256']==expected
            if valid:
                identity=(result['systemd']['MainPID'],result['systemd']['InvocationID'])
                stable=stable+1 if first==identity else 1
                first=identity
                if stable>=5:return result
            else:
                stable=0;first=None
            if result['state'] in {'stopped','failed'}:break
            time.sleep(.1)
        raise Denied('HEALTH_FAILED')

    def validate(self, candidate):
        binary=Path('/opt/bridge-official/dae')
        before=digest(binary.read_bytes())
        check(before==self.policy['validateBinarySha256'],'VALIDATOR_HASH')
        r=subprocess.run([str(binary),'validate','-c',str(candidate)],env=ENV,capture_output=True,timeout=30)
        check(digest(binary.read_bytes())==before,'VALIDATOR_CHANGED')
        check(r.returncode==0,'VALIDATE_FAILED')
        return {'exitCode':r.returncode,'binarySha256':before,'output':'[REDACTED]'}


class Controller:
    def __init__(self, base, policy, service, now=time.time, checkpoint=lambda _:None, policy_provider=None, bundle_verifier=verify_bundle):
        self.base,self.policy,self.service,self.now,self.checkpoint=base,policy,service,now,checkpoint
        self.policy_provider=policy_provider
        self.bundle_verifier=bundle_verifier

    def pointer(self):
        p=self.base/'current'
        if not p.is_symlink():
            check(not p.exists(),'POINTER_TYPE');return None
        target=os.readlink(p)
        check(target.startswith('versions/') and HEX.fullmatch(target[9:]) is not None,'POINTER_TARGET')
        return target[9:]

    def switch(self, identity):
        p=self.base/'current'
        tmp=self.base/'current.next';tmp.unlink(missing_ok=True)
        if identity is None:p.unlink(missing_ok=True)
        else:
            os.symlink('versions/'+identity,tmp);os.replace(tmp,p)
        syncdir(self.base)

    def record(self, **value):atomic_json(self.base/'transaction.json',value)

    def journal(self):
        if not (self.base/'transaction.json').exists():return None
        fd=directory(self.base,0,0,0o711)
        try:return load_json(read_at(fd,'transaction.json',0,0))
        finally:os.close(fd)

    def candidate(self, identity):return self.base/'versions'/identity/'candidate.dae'

    def version(self, identity):
        files=read_set(self.base/'versions'/identity,0,0,FILES|{'bundle.json'},0o400)
        # The root-owned accepted version can outlive its receipt, but never its content hash.
        check(digest(files['bundle.json'])==identity,'VERSION_ID')
        envelope=load_json(files['bundle.json'])
        check(envelope['files']=={n:digest(files[n]) for n in sorted(FILES)},'VERSION_HASH')
        return digest(files['candidate.dae'])

    def healthy(self, identity):return self.service.healthy(self.candidate(identity),self.version(identity))

    def rollback(self, transaction):
        previous=transaction['previous']
        self.service.verify_unit()
        # An unchanged pointer plus the exact pre-transaction live identity needs no restart.
        if self.pointer()==previous:
            try:
                obs=self.service.observe(self.candidate(previous) if previous else None)
                if transaction['previousServiceState']=='running':
                    obs=self.healthy(previous)
                    check(self.process_identity(obs)==transaction.get('previousIdentity'),'PROCESS_CHANGED')
                else:self.stopped(obs,'STATE_CHANGED')
                self.record(**dict(transaction,phase='ROLLED_BACK'))
                return {'state':obs['state'],'result':'ROLLED_BACK','activeBundle':previous,'observation':obs,'recoveryMode':'UNCHANGED'}
            except Exception:pass
        self.record(**dict(transaction,phase='ROLLING_BACK'))
        try:
            self.service.command('stop')
            self.switch(previous)
            if previous:self.version(previous)
            if transaction['previousServiceState']=='running':
                check(previous is not None,'PREVIOUS_BUNDLE_REQUIRED')
                self.service.validate(self.candidate(previous))
                self.service.command('start');status=self.healthy(previous)
            else:
                status=self.service.observe(None)
                if status['state']=='failed' and status.get('systemd',{}).get('MainPID')=='0':
                    # Only an owned rollback to previously stopped may clear a failed latch.
                    self.service.command('reset-failed');status=self.service.observe(None)
                self.stopped(status,'STOP_NOT_CONFIRMED')
            self.record(**dict(transaction,phase='ROLLED_BACK'))
            return {'state':status['state'],'result':'ROLLED_BACK','activeBundle':previous,'observation':status}
        except Exception:
            self.record(**dict(transaction,phase='ROLLBACK_FAILED'))
            return {'state':'rollback-needed','result':'MANUAL_INTERVENTION_REQUIRED','activeBundle':self.pointer()}

    def execute(self, value):
        for folder,mode in ((self.base,0o711),(self.base/'versions',0o700)):
            fd=directory(folder,0,0,mode);os.close(fd)
        # Read-only observations never compete with mutations for the write lock.
        # locked(status) verifies the pointer/journal did not change while reading.
        if value['action']=='status':return self.locked(value)
        lockfd=os.open(self.base/'apply.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            st=os.fstat(lockfd)
            check(st.st_uid==0 and st.st_gid==0 and st.st_nlink==1 and st.st_mode & 0o777==0o600,'LOCK_AUTHORITY')
            try:fcntl.flock(lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise Denied('BUSY')
            return self.locked(value)
        finally:os.close(lockfd)

    @staticmethod
    def process_identity(obs):
        raw=obs.get('systemd',{})
        return {'MainPID':raw.get('MainPID'),'InvocationID':raw.get('InvocationID'),'configSha256':obs.get('configSha256')}

    @staticmethod
    def stopped(obs, code):
        check(obs.get('state')=='stopped' and obs.get('systemd',{}).get('ActiveState')=='inactive'
              and obs.get('systemd',{}).get('MainPID')=='0',code)

    def service_state(self, current, allow_failed_start=False):
        try:obs=self.service.observe(self.candidate(current) if current else None)
        except Exception:
            if not current:raise Denied('UNMANAGED_SERVICE_ACTIVE') from None
            raise
        if not current:
            self.stopped(obs,'UNMANAGED_SERVICE_ACTIVE');self.previous_identity=None;return 'stopped'
        self.version(current)
        if obs['state']=='stopped':
            self.stopped(obs,'SERVICE_STATE_UNKNOWN');self.previous_identity=None;return 'stopped'
        if obs['state']=='failed' and allow_failed_start:
            raw=obs.get('systemd',{})
            check(raw.get('ActiveState')=='failed' and raw.get('MainPID')=='0','MANUAL_INTERVENTION_REQUIRED')
            self.previous_identity=None
            return 'stopped'
        check(obs['state']!='failed','MANUAL_INTERVENTION_REQUIRED')
        self.previous_identity=self.process_identity(self.healthy(current))
        return 'running'

    def locked(self, value):
        action,identity=value['action'],value.get('bundleId')
        journal=self.journal();current=self.pointer()
        interrupted=journal and journal['phase'] not in {'HEALTHY','ROLLED_BACK','STOPPED'}
        if action=='status':
            obs=self.service.observe(self.candidate(current) if current else None)
            if current:
                try:
                    expected=self.version(current)
                    check(not obs.get('identityVerified') or obs['configSha256']==expected,'CURRENT_VERSION_INVALID')
                except Exception:obs.update(state='rollback-needed',identityVerified=False,error='CURRENT_VERSION_INVALID')
            try:self.service.verify_unit()
            except Exception:obs.update(state='rollback-needed',error='UNIT_IDENTITY_MISMATCH')
            if current and not interrupted and obs['state']=='failed':obs['result']='MANUAL_INTERVENTION_REQUIRED'
            raw=obs.get('systemd',{})
            obs.update(activeBundle=current,requestedBundle=identity,
                       matchesRequestedBundle=(current==identity if identity else None),
                       MainPID=int(raw.get('MainPID',0)),InvocationID=raw.get('InvocationID',''),
                       executableSha256=obs.get('executableSha256'),configSha256=obs.get('configSha256'))
            if interrupted:obs.update(state='rollback-needed',result='RECOVERY_REQUIRED',phase=journal['phase'])
            check(self.pointer()==current and self.journal()==journal,'BUSY')
            return obs
        self.service.verify_unit()
        if action=='recover':
            check(interrupted,'NO_PENDING_RECOVERY')
            check(identity in {journal['candidate'],journal['previous']},'RECOVERY_BUNDLE_CONFLICT')
            return self.rollback(journal)
        check(not interrupted,'RECOVERY_REQUIRED')
        if action=='apply' and current==identity:
            return dict(self.healthy(identity),result='ALREADY_APPLIED',activeBundle=current)
        previous_state=self.service_state(current,allow_failed_start=action=='start')
        if action in {'start','stop','reload'}:
            check(identity==current and current is not None,'CURRENT_CONFLICT')
            if (action=='start' and previous_state=='running') or (action=='stop' and previous_state=='stopped'):
                return {'state':previous_state,'result':'ALREADY_'+previous_state.upper(),'activeBundle':current}
            check(action!='reload' or previous_state=='running','SERVICE_NOT_RUNNING')
            if action=='start':self.service.validate(self.candidate(current))
            tx={'candidate':identity,'previous':current,'previousServiceState':previous_state,'previousIdentity':self.previous_identity,'phase':'ACTIVATING'}
            self.record(**tx);self.checkpoint('before-action')
            try:
                if action=='start':
                    # Explicit start of a verified, managed bundle may clear a crashed
                    # unit only after the transaction is durable and MainPID is zero.
                    observed=self.service.observe(self.candidate(current))
                    if observed['state']=='failed':
                        raw=observed.get('systemd',{})
                        check(raw.get('ActiveState')=='failed' and raw.get('MainPID')=='0','MANUAL_INTERVENTION_REQUIRED')
                        self.service.command('reset-failed')
                        self.stopped(self.service.observe(self.candidate(current)),'STOP_NOT_CONFIRMED')
                    else:self.stopped(observed,'SERVICE_STATE_CHANGED')
                self.service.command(action);self.checkpoint('after-action')
                obs=self.service.observe(None) if action=='stop' else self.healthy(current)
                if action=='stop':self.stopped(obs,'STOP_NOT_CONFIRMED')
                self.record(**dict(tx,phase='STOPPED' if action=='stop' else 'HEALTHY'))
                return obs
            except Exception:return self.rollback(tx)
        check(not current or previous_state=='running','SERVICE_NOT_RUNNING')
        payload=read_set(self.base/'inbox'/identity,self.policy['bridgeUid'],self.policy['bridgeGid'],FILES|{'bundle.json'},0o400)
        envelope=self.bundle_verifier(payload,identity,self.policy['receipt'],int(self.now()))
        check(envelope['expectedCurrent']==current,'CURRENT_CONFLICT')
        if current:self.healthy(current)
        target=self.base/'versions'/identity
        if target.exists():
            check(read_set(target,0,0,FILES|{'bundle.json'},0o400)==payload,'VERSION_CONFLICT')
        else:
            staged=target.with_name('.'+identity+'-'+str(os.getpid()))
            staged.mkdir(mode=0o700)
            for name,body in payload.items():write_file(staged/name,body,0o400)
            syncdir(staged)
            os.rename(staged,target);syncdir(target.parent)
        validation=self.service.validate(target/'candidate.dae')
        fresh=self.policy_provider() if self.policy_provider else self.policy
        check(fresh==self.policy,'POLICY_CHANGED')
        self.bundle_verifier(payload,identity,fresh['receipt'],int(self.now()))
        check(self.service_state(current)==previous_state,'SERVICE_STATE_CHANGED')
        tx={'candidate':identity,'previous':current,'previousServiceState':previous_state,'previousIdentity':self.previous_identity,'phase':'PREPARED','validation':validation}
        self.record(**tx);self.checkpoint('before-switch')
        self.switch(identity);self.record(**dict(tx,phase='PUBLISHED'));self.checkpoint('after-switch')
        try:
            self.record(**dict(tx,phase='ACTIVATING'))
            if previous_state=='running':self.service.command('stop')
            self.service.command('start')
            self.checkpoint('after-start')
            obs=self.healthy(identity)
            self.record(**dict(tx,phase='HEALTHY'))
            return dict(obs,result='APPLIED',activeBundle=identity)
        except Exception:return self.rollback(tx)
