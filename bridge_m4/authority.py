"""Root-owned installed-file authority and fixed independent DAE control adapter."""
import json
import hashlib
import stat
import os
from pathlib import Path
import pwd
import grp
from bridge_m2.control import BASE, ENV, Systemd as OriginalSystemd, Controller
from bridge_m2.security import check, directory,read_at,digest,load_json
from .runtime_bundle import verify_bundle

MANIFEST=Path('/etc/daed-independent-bridge/install.json')
_OBSERVED_DIGESTS={}

PUBLIC=Path('/var/lib/bridge-m4-attestation')

def digest_at(fd, name, uid, gid, mode=0o600, limit=4 * 1024 * 1024, observation=False):
    """Strict full SHA by default; observation may reuse an unchanged file digest."""
    check('/' not in name and name not in ('.', '..'), 'PATH_REJECTED')
    filefd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(filefd)
        check(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'FILE_TYPE')
        check(before.st_uid == uid and before.st_gid == gid and stat.S_IMODE(before.st_mode) == mode, 'FILE_AUTHORITY')
        check(before.st_size <= limit, 'SIZE_LIMIT')
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink, s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode))
        key = identity(before)
        if observation and key in _OBSERVED_DIGESTS:
            after = os.fstat(filefd)
            linked = os.stat(name, dir_fd=fd, follow_symlinks=False)
            check(key == identity(after) == identity(linked), 'SOURCE_RACE')
            return _OBSERVED_DIGESTS[key]
        hasher = hashlib.sha256()
        length = 0
        while length <= before.st_size:
            chunk = os.read(filefd, min(1024 * 1024, before.st_size + 1 - length))
            if not chunk:
                break
            length += len(chunk)
            hasher.update(chunk)
        after = os.fstat(filefd)
        linked = os.stat(name, dir_fd=fd, follow_symlinks=False)
        check(identity(before) == identity(after) == identity(linked) and length == before.st_size, 'SOURCE_RACE')
        value = hasher.hexdigest()
        if len(_OBSERVED_DIGESTS) >= 4096:
            _OBSERVED_DIGESTS.clear()
        _OBSERVED_DIGESTS[key] = value
        return value
    finally:
        os.close(filefd)

def manifest(*, verify_all_assets=False, observation=False):
    fd=directory(MANIFEST.parent,0,0,0o755)
    try:record=load_json(read_at(fd,MANIFEST.name,0,0,0o644))
    finally:os.close(fd)
    check(type(record) is dict and set(record)=={'schemaVersion','files'} and record['schemaVersion']==1,'INSTALL_MANIFEST')
    check(type(record['files']) is dict and bool(record['files']),'INSTALL_MANIFEST')
    for name,pin in record['files'].items():
        path=Path(name)
        check(path.is_absolute() and '..' not in path.parts and type(pin) is dict and set(pin)=={'sha256','mode'},'INSTALL_MANIFEST')
        check(name=='/etc/dae-dns-repair/sync_policy_independent.py' or name.startswith(('/opt/bridge-daed-web/','/opt/bridge-daed-web-entry/','/opt/bridge/','/usr/local/bin/bridge-','/etc/systemd/system/','/etc/tmpfiles.d/bridge-','/opt/bridge-official/','/opt/bridge-service/')),'INSTALL_PATH')
        from .asset_authority import ASSET_FILES
        if not verify_all_assets and name in ASSET_FILES:
            continue
        parent=directory(path.parent,0,0,0o755)
        try:actual=digest_at(parent,path.name,0,0,pin['mode'],limit=150*1024*1024,observation=observation)
        finally:os.close(parent)
        check(actual==pin['sha256'],'INSTALL_FILE_IDENTITY')
    return record

def policy(observation=False):
    check(os.geteuid()==0,'ROOT_HELPER_REQUIRED')
    installed=manifest(observation=observation)
    from .asset_authority import verify_active_assets
    verify_active_assets(installed)
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
    def __init__(self, policy, observation=False):
        super().__init__(policy)
        self.observation = observation
    def validate(self,candidate):
        manifest()
        from .validation import validate
        return validate(candidate,self.policy["validateBinarySha256"])

    def verify_unit(self):
        manifest(observation=self.observation)
        return super().verify_unit()

class M4Controller(Controller):
    def execute(self, value):
        check(not self.service.observation or value.get('action') == 'status', 'OBSERVATION_ONLY')
        return super().execute(value)
    def locked(self,value):
        result=super().locked(value)
        if value['action']=='status':
            active=result.get('activeBundle')
            if active and not result.get('error'):
                fd=directory(self.base/'versions'/active,0,0,0o700)
                try:sealed=load_json(read_at(fd,'manifest.json',0,0,0o400))
                finally:os.close(fd)
                check(self.pointer()==active,'SOURCE_CHANGED')
                result['sourceFingerprint']=sealed['sourceSha256']
            journal=self.journal()
            if journal and journal['phase'] not in {'HEALTHY','ROLLED_BACK','STOPPED'}:
                result['recoveryBundle']=journal['candidate']
        return result

def controller(p, observation=False):return M4Controller(BASE,p,Systemd(p, observation=observation),policy_provider=policy,bundle_verifier=verify_bundle)
