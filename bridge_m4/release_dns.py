"""Packaged DNS integration, using the existing verified status decision."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from .dns_sync_runtime import read_status
from .dns_sync import reconcile
from .dnsdist_control import DnsdistControl
from .release_policy import generate
CFG=Path('/etc/daed-independent-bridge')

class Backends:
    def __init__(self):
        self.control=DnsdistControl(('/usr/bin/dnsdist','-C',str(CFG/'lan-dns.conf'),'-c'))
    def states(self):
        servers=self.control.servers()
        if set(servers)!={'DAE','DIRECT'}:raise RuntimeError('DNS_BACKEND_IDENTITY')
        return {k:v.state for k,v in servers.items()}
    def set_state(self,name,state):
        if name not in {'DAE','DIRECT'}:raise RuntimeError('DNS_BACKEND_IDENTITY')
        self.control.set_state(self.control.servers()[name],state)


def policy():
    with open('/run/bridge-policy-sync.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before,expected=read_status()
        if before.get('identityVerified') is not True or before.get('state')!='running' or before.get('configSha256')!=expected:
            raise RuntimeError('DAE_IDENTITY')
        # read_status has verified the entire root-owned active bundle.
        bundle=Path('/var/lib/daed-independent-bridge/versions')/before['activeBundle']
        ir=json.loads((bundle/'normalized-ir.json').read_text())
        routing=''.join(t['text'] for t in ir['routing']['tokens'])
        settings=json.loads((CFG/'release.json').read_text())
        output=generate(routing,settings['providers'],Path('/opt/bridge-official/assets/geosite.dat'))
        target=CFG/'policy-dns.conf'
        if target.read_bytes()==output:
            print('{"changed":false,"source":"INDEPENDENT_BRIDGE"}');return
        temp=target.with_suffix('.next');temp.write_bytes(output);temp.chmod(0o644)
        try:
            subprocess.run(['/usr/bin/dnsdist','--check-config','-C',str(temp)],check=True,capture_output=True,timeout=15)
            after,again=read_status()
            if after.get('activeBundle')!=before['activeBundle'] or again!=expected or after.get('identityVerified') is not True:
                raise RuntimeError('SOURCE_CHANGED')
            old=target.read_bytes();os.replace(temp,target)
            try:subprocess.run(['/usr/bin/systemctl','restart','bridge-policy-dns.service'],check=True,capture_output=True,timeout=30)
            except subprocess.SubprocessError:
                target.write_bytes(old)
                subprocess.run(['/usr/bin/systemctl','restart','bridge-policy-dns.service'],check=True,capture_output=True,timeout=30)
                raise
        finally:temp.unlink(missing_ok=True)
        print('{"changed":true,"source":"INDEPENDENT_BRIDGE"}')


def main():
    try:
        if sys.argv[1:]==['policy']:policy();return 0
        if sys.argv[1:]!=['sync']:raise RuntimeError('ACTION_REJECTED')
        result=reconcile(read_status,Backends())
        print(json.dumps(result));return 0 if result['consistent'] else 1
    except Exception:
        print('{"passed":false,"error":"DNS_SYNC_FAILED"}');return 1

if __name__=='__main__':raise SystemExit(main())
