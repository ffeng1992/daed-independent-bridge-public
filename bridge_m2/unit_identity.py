"""Fixed dae.service authority, separate from its transient process state."""
import os
from pathlib import Path
import re
import subprocess
from .security import check, digest, directory, read_at, Denied

FILES={
    '/etc/systemd/system/dae.service':0o644,
    '/usr/local/bin/bridge-runner':0o755,
    '/opt/bridge/bridge_m2/runner.py':0o644,
    '/opt/bridge-service/dae':0o555,
}

def snapshot(env):
    raw=subprocess.run(['/usr/bin/systemctl','show','dae.service','--no-pager','--property=FragmentPath,DropInPaths,ExecStart,ExecReload,NeedDaemonReload'],env=env,capture_output=True,timeout=5)
    check(raw.returncode==0,'UNIT_IDENTITY_MISMATCH')
    fields=dict(line.split('=',1) for line in raw.stdout.decode().splitlines() if '=' in line)
    check(fields.get('FragmentPath')=='/etc/systemd/system/dae.service' and fields.get('DropInPaths')=='' and fields.get('NeedDaemonReload')=='no','UNIT_IDENTITY_MISMATCH')
    for key in ('ExecStart','ExecReload'):
        value=fields[key]
        commands=re.findall(r'\{ path=(.*?) ; argv\[\]=(.*?) ; ignore_errors=(yes|no) ;',value)
        check((not value and key=='ExecReload') or len(commands)==1,'UNIT_IDENTITY_MISMATCH')
        fields[key]=[list(command) for command in commands]
    hashes={}
    for name,mode in FILES.items():
        path=Path(name);parent=directory(path.parent,0,0,0o755)
        try:body=read_at(parent,path.name,0,0,mode=mode,limit=100*1024*1024)
        finally:os.close(parent)
        hashes[name]=digest(body)
    return {'properties':fields,'files':hashes}


def verify(policy,env):
    try:
        observed=snapshot(env)
        check(observed==policy.get('serviceIdentity'),'UNIT_IDENTITY_MISMATCH')
        check(observed['files']['/opt/bridge-service/dae']==policy['serviceBinarySha256'],'UNIT_IDENTITY_MISMATCH')
        return observed
    except Exception:
        raise Denied('UNIT_IDENTITY_MISMATCH') from None
