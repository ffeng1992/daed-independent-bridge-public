"""Independent read-only source/identity observer; writes only derived receipts."""
import fcntl
import os
import json
from pathlib import Path
import subprocess
import time
from bridge_m1.collect import HTTPReader
from bridge_m1.common import canonical,digest,load_json
from bridge_m2.control import BASE,ENV
from bridge_m2.security import check,directory,read_at,syncdir,write_file
from .collect import collect
from .runtime import EXTENSIONS,ENDPOINT,PUBLIC
from .runtime_bundle import receipt,fingerprints
from .authority import policy,manifest,controller

def identity():
    result=subprocess.run(['/usr/bin/systemctl','show','daed-api.service','--property=MainPID,InvocationID,ActiveState'],env=ENV,capture_output=True,check=True,timeout=5)
    raw=dict(line.split('=',1) for line in result.stdout.decode().splitlines() if '=' in line)
    check(raw['ActiveState']=='active' and int(raw['MainPID'])>0,'DAED_IDENTITY')
    pid=raw['MainPID'];binary=digest(Path(f'/proc/{pid}/exe').read_bytes())
    lock=load_json(Path('/opt/bridge/upstream.lock.json').read_bytes())
    expected=next(x['sha256'] for x in lock['components']['daed']['archive_members'] if x['path'].endswith('/daed-linux-x86_64'))
    argv=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[:-1]
    check(binary==expected and argv==[b'/opt/bridge-official/daed',b'run',b'--api-only',b'--config',b'/var/lib/bridge-daed',b'--listen',b'127.0.0.1:2024'],'DAED_IDENTITY')
    inodes={line.split()[9] for line in Path('/proc/net/tcp').read_text().splitlines()[1:] if line.split()[1]=='0100007F:07E8' and line.split()[3]=='0A'}
    links={os.readlink(p) for p in Path(f'/proc/{pid}/fd').iterdir()}
    check(any('socket:['+i+']' in links for i in inodes),'DAED_LISTENER')
    return dict(raw,binarySha256=binary)

def extensions(p):
    fd=directory(EXTENSIONS,p['bridgeUid'],p['bridgeGid'])
    try:
        generation=read_at(fd,'current',p['bridgeUid'],p['bridgeGid']).decode().strip()
        check(len(generation)==64 and all(c in '0123456789abcdef' for c in generation),'EXTENSION_POINTER')
        body=read_at(fd,generation+'.json',p['bridgeUid'],p['bridgeGid'])
        check(digest(body)==generation,'EXTENSION_INTEGRITY')
        value=load_json(body)
        return generation,value['extensions']
    finally:os.close(fd)

def attest():
    p=policy();before=identity();generation,ext=extensions(p)
    fd=directory('/etc/daed-independent-bridge',0,0,0o755)
    try:token=read_at(fd,'attestor.token',0,0).decode().strip()
    finally:os.close(fd)
    source,proof=collect(HTTPReader(ENDPOINT,token))
    after=identity();next_generation,_=extensions(p)
    check(before==after and generation==next_generation,'SOURCE_CHANGED')
    from .convert import bind_new_profiles
    fingerprints(source,ext)
    ext=bind_new_profiles(source,ext)
    now=int(time.time());pins=fingerprints(source,ext)
    if p['receipt'] and all(p['receipt'].get(k)==v for k,v in pins.items()) and p['receipt'].get('expiresAt',0)-now>=60:return
    lock=os.open(BASE/'apply.lock',os.O_RDWR|os.O_NOFOLLOW)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        check(extensions(p)[0]==generation and identity()==after,'SOURCE_CHANGED')
        # Source can evolve after observation; the receipt is bounded to 180 seconds.
        value=receipt(source,ext,now)
        temp=PUBLIC/'receipt.next';temp.unlink(missing_ok=True)
        write_file(temp,canonical(value),0o640);os.chown(temp,0,p['bridgeGid'])
        os.replace(temp,PUBLIC/'receipt.json');syncdir(PUBLIC)
    finally:os.close(lock)

def observe_kernel():
    # Separate evidence file: volatile observations must not alter status identity.
    from .kernel_observations import observe
    p=policy();state=controller(p).execute({'action':'status'})
    check(state.get('identityVerified') and state['state']=='running','DAE_IDENTITY')
    value=observe(state['MainPID']);value['InvocationID']=state['InvocationID']
    after=controller(p).execute({'action':'status'})
    check(after.get('identityVerified') and after['MainPID']==state['MainPID'] and
          after['InvocationID']==state['InvocationID'],'DAE_IDENTITY_CHANGED')
    temp=PUBLIC/'kernel-observations.next';temp.unlink(missing_ok=True)
    write_file(temp,canonical(value),0o640);os.chown(temp,0,p['bridgeGid'])
    os.replace(temp,PUBLIC/'kernel-observations.json');syncdir(PUBLIC)

def main():
    while True:
        try:observe_kernel()
        except Exception:
            print('{"kernelObservation":"unavailable"}',flush=True)
        try:attest();print('{"attestor":"observed"}',flush=True)
        except Exception as exc:
            from .diagnostics import failure
            failure('attestor',exc)
            print('{"attestor":"unavailable","receiptNotIssued":true}',flush=True)
        time.sleep(5)
if __name__=='__main__':main()
