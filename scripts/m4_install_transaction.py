"""Root installer journal, independent of dataplane apply transactions."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import time

ROOT=Path('/var/lib/bridge-m4-install')
ALLOWED=('/opt/bridge-daed-web/','/opt/bridge-daed-web-entry/','/opt/bridge/','/opt/bridge-official/','/opt/bridge-service/','/usr/local/bin/bridge-','/etc/systemd/system/','/etc/tmpfiles.d/bridge-')
EXACT={'/etc/daed-independent-bridge/install.json','/var/lib/daed-independent-bridge/policy.json'}

OPTIONAL_EXACT={'/etc/dae-dns-repair/sync_policy_independent.py'}

def allowed(name):return name in EXACT or name in OPTIONAL_EXACT or name.startswith(ALLOWED)

def need(value):
    if not value:raise RuntimeError('INSTALL_MANUAL_INTERVENTION_REQUIRED')
def sha(data):return hashlib.sha256(data).hexdigest()
def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
def write(path,body,mode):
    temp=path.with_name(path.name+'.restore-new')
    if temp.exists() or temp.is_symlink():
        st=temp.lstat();need(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1)
        temp.unlink()
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        with os.fdopen(fd,'wb',closefd=False) as f:f.write(body);f.flush();os.fsync(fd)
    finally:os.close(fd)
    temp.chmod(mode);os.replace(temp,path);sync(path.parent)
def journal(value):write(ROOT/'transaction.json',(json.dumps(value,sort_keys=True)+'\n').encode(),0o600)
def load():
    path=ROOT/'transaction.json'
    if not path.exists():return None
    need(not path.is_symlink() and path.stat().st_uid==0 and stat.S_IMODE(path.stat().st_mode)==0o600)
    return json.loads(path.read_text())
@contextmanager
def exclusive():
    ROOT.mkdir(mode=0o700,exist_ok=True)
    st=ROOT.lstat()
    need(stat.S_ISDIR(st.st_mode) and st.st_uid==0 and st.st_gid==0 and stat.S_IMODE(st.st_mode)==0o700)
    fd=os.open(ROOT/'install.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        st=os.fstat(fd)
        need(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_gid==0 and st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o600)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('INSTALL_BUSY') from None
        yield
    finally:os.close(fd)

def begin(paths):
    ROOT.mkdir(mode=0o700,exist_ok=True)
    need(not ROOT.is_symlink() and ROOT.stat().st_uid==0 and stat.S_IMODE(ROOT.stat().st_mode)==0o700)
    previous=load();need(not previous or previous['phase'] in {'COMMITTED','RESTORED'})
    generation=str(time.time_ns());backup=ROOT/generation;backup.mkdir(mode=0o700)
    records=[]
    for index,name in enumerate(sorted(set(paths)|EXACT)):
        need(allowed(name));p=Path(name)
        need('..' not in p.parts and not p.is_symlink())
        item={'path':name,'backup':None}
        if p.exists():
            st=p.stat();need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==0 and st.st_gid==0)
            body=p.read_bytes();filename=str(index)+'.blob'
            fd=os.open(backup/filename,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
            item.update(backup=filename,sha256=sha(body),mode=stat.S_IMODE(st.st_mode))
        records.append(item)
    sync(backup);journal({'phase':'APPLYING','generation':generation,'files':records})
def commit():
    value=load();need(value is not None and value['phase']=='APPLYING');value['phase']='COMMITTED';journal(value)
def restore():
    value=load();need(value is not None and value['phase'] in {'APPLYING','RESTORING','COMMITTED'})
    value['phase']='RESTORING';journal(value)
    need(value['generation'].isdecimal());backup=ROOT/value['generation']
    for item in value['files']:
        name=item['path'];need(allowed(name));p=Path(name)
        need('..' not in p.parts and not p.is_symlink())
        if item['backup'] is None:
            p.unlink(missing_ok=True)
            if p.parent.exists():sync(p.parent)
        else:
            need('/' not in item['backup'] and item['backup'].endswith('.blob'))
            body=(backup/item['backup']).read_bytes();need(sha(body)==item['sha256'])
            write(p,body,item['mode'])
    value['phase']='RESTORED';journal(value)
