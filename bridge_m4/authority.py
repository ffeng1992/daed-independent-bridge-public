"""Root-owned installed-file authority and fixed independent DAE control adapter."""
import json
import os
from pathlib import Path
import pwd
import grp
from bridge_m2.control import BASE, ENV, Systemd as OriginalSystemd, Controller
from bridge_m2.security import check, directory,read_at,digest,load_json
from .runtime_bundle import verify_bundle

MANIFEST=Path('/etc/daed-independent-bridge/install.json')
PUBLIC=Path('/var/lib/bridge-m4-attestation')

def manifest():
    fd=directory(MANIFEST.parent,0,0,0o755)
    try:record=load_json(read_at(fd,MANIFEST.name,0,0,0o644))
    finally:os.close(fd)
    check(type(record) is dict and set(record)=={'schemaVersion','files'} and record['schemaVersion']==1,'INSTALL_MANIFEST')
    check(type(record['files']) is dict and bool(record['files']),'INSTALL_MANIFEST')
    for name,pin in record['files'].items():
        path=Path(name)
        check(path.is_absolute() and '..' not in path.parts and type(pin) is dict and set(pin)=={'sha256','mode'},'INSTALL_MANIFEST')
        check(name=='/etc/dae-dns-repair/sync_policy_independent.py' or name.startswith(('/opt/bridge-daed-web/','/opt/bridge-daed-web-entry/','/opt/bridge/','/usr/local/bin/bridge-','/etc/systemd/system/','/etc/tmpfiles.d/bridge-','/opt/bridge-official/','/opt/bridge-service/')),'INSTALL_PATH')
        parent=directory(path.parent,0,0,0o755)
        try:body=read_at(parent,path.name,0,0,pin['mode'],limit=150*1024*1024)
        finally:os.close(parent)
        check(digest(body)==pin['sha256'],'INSTALL_FILE_IDENTITY')
    return record

def policy():
    check(os.geteuid()==0,'ROOT_HELPER_REQUIRED')
    manifest()
    fd=directory(BASE,0,0,0o711)
    try:p=load_json(read_at(fd,'policy.json',0,0))
    finally:os.close(fd)
    check(p['bridgeUid']==pwd.getpwnam('independent-bridge').pw_uid and p['bridgeGid']==grp.getgrnam('independent-bridge').gr_gid,'BRIDGE_IDENTITY')
    fd=directory(PUBLIC,0,p['bridgeGid'],0o750)
    try:
        try:p['receipt']=load_json(read_at(fd,'receipt.json',0,p['bridgeGid'],0o640))
        except FileNotFoundError:p['receipt']=None # status and recovery do not require a receipt; apply fails closed
    finally:os.close(fd)
    return p

class Systemd(OriginalSystemd):
    def validate(self,candidate):
        manifest()
        from .validation import validate
        return validate(candidate,self.policy["validateBinarySha256"])

    def verify_unit(self):
        manifest()
        return super().verify_unit()

class M4Controller(Controller):
    def locked(self,value):
        result=super().locked(value)
        if value['action']=='status':
            journal=self.journal()
            if journal and journal['phase'] not in {'HEALTHY','ROLLED_BACK','STOPPED'}:
                result['recoveryBundle']=journal['candidate']
        return result

def controller(p):return M4Controller(BASE,p,Systemd(p),policy_provider=policy,bundle_verifier=verify_bundle)
