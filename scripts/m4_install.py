"""Fixed-path offline install candidate. Never starts a service or adopts active DAE.

Run only in disposable Debian during M4. Upgrade/uninstall require every owned
service to be inactive and the control socket stopped. Configuration/state remain
for explicit restore; an installer does not silently delete databases or bundles.
"""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import hashlib
import stat

ROOT=Path(__file__).resolve().parents[1]
UNITS=('dae.service','daed-api.service','bridge-helper.socket','bridge-helper.service','bridge-attestor.service','independent-bridge.service')
PACKAGE_DIRS=('bridge_m1','bridge_m2','bridge_m4','contracts','queries')
BASE=Path('/var/lib/daed-independent-bridge')
MANIFEST=Path('/etc/daed-independent-bridge/install.json')

def check(value,code):
    if not value:raise RuntimeError(code)
def digest(body):return hashlib.sha256(body).hexdigest()
def ctl(*args):return subprocess.run(['/usr/bin/systemctl',*args],capture_output=True,check=True,timeout=20)

def quiescent():
    from scripts.m4_production_dns import UNITS as DNS_UNITS
    for name in UNITS+DNS_UNITS+('bridge-lan-dns.service','bridge-policy-dns.service','daed-web.service'):
        r=ctl('show',name,'--property=ActiveState,MainPID')
        d=dict(line.split('=',1) for line in r.stdout.decode().splitlines() if '=' in line)
        check(d.get('ActiveState')=='inactive' and d.get('MainPID','0')=='0','INSTALL_REQUIRES_INACTIVE_SERVICES')

def account(name):
    try:entry=pwd.getpwnam(name)
    except KeyError:
        subprocess.run(['/usr/sbin/useradd','--system','--no-create-home','--home-dir','/nonexistent','--shell','/usr/sbin/nologin',name],check=True)
        entry=pwd.getpwnam(name)
    check(entry.pw_uid!=0 and entry.pw_shell=='/usr/sbin/nologin' and grp.getgrgid(entry.pw_gid).gr_name==name,'ACCOUNT_AUTHORITY')
    return entry.pw_uid,entry.pw_gid

def folder(path,mode,uid=0,gid=0):
    path=Path(path)
    # Existing unexpected owners/modes are refused rather than silently adopted.
    if path.exists():
        st=path.lstat();check(path.is_dir() and not path.is_symlink() and (st.st_uid,st.st_gid,st.st_mode&0o777)==(uid,gid,mode),'DIRECTORY_AUTHORITY')
    else:path.mkdir(mode=mode);os.chown(path,uid,gid);path.chmod(mode)

def payload(production_dns=False,release_profile=False):
    files={}
    for directory in PACKAGE_DIRS:
        for p in sorted((ROOT/directory).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':
                check(not p.is_symlink(),'SOURCE_LINK');files['/opt/bridge/'+str(p.relative_to(ROOT))]=(p.read_bytes(),0o644)
    check((ROOT/'out/m4-vendor').is_dir(),'OFFLINE_DEPENDENCIES_REQUIRED')
    for p in sorted((ROOT/'out/m4-vendor').rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'):
            check(not p.is_symlink(),'DEPENDENCY_LINK')
            files['/opt/bridge/vendor/'+str(p.relative_to(ROOT/'out/m4-vendor'))]=(p.read_bytes(),0o644)
    for name in ('upstream.lock.json',):files['/opt/bridge/'+name]=((ROOT/name).read_bytes(),0o644)
    for name in UNITS:files['/etc/systemd/system/'+name]=((ROOT/'deployment/m4/units'/name).read_bytes(),0o644)
    for name,module,call in [('runner','runner','main'),('broker','broker','serve'),('attestor','attestor','main'),('web','web','main')]:
        files['/usr/local/bin/bridge-'+name]=(('import sys\nsys.dont_write_bytecode=True\nsys.path.insert(0,"/opt/bridge/vendor")\nsys.path.insert(0,"/opt/bridge")\nfrom bridge_m4.'+module+' import '+call+'\n'+call+'()\n').encode(),0o755)
    files['/etc/tmpfiles.d/bridge-m4.conf']=(b'd /run/bridge-control 0710 root independent-bridge -\n',0o644)
    lock=json.loads((ROOT/'upstream.lock.json').read_text())
    for name in ('daed','dae'):
        binary=ROOT/'out/m2-official'/name
        member=next(x for x in lock['components'][name]['archive_members'] if x['path'].endswith(name+'-linux-x86_64'))
        body=binary.read_bytes();check(digest(body)==member['sha256'],'OFFICIAL_BINARY_HASH')
        files['/opt/bridge-official/'+name]=(body,0o555)
        if name=='dae':files['/opt/bridge-service/dae']=(body,0o555)
    from scripts.m4_assets import official_assets
    for name,body in official_assets((ROOT/"official/dae.zip").read_bytes(),lock["components"]["dae"]).items():
        files["/opt/bridge-official/assets/"+name]=(body,0o444)
    if production_dns:
        from scripts.m4_production_dns import payload as dns_payload
        files.update(dns_payload(ROOT))
    if release_profile:
        from scripts.release_payload import payload as release_payload
        files.update(release_payload(ROOT))
    return files

def verify_installed(record):
    for name,pin in record['files'].items():
        path=Path(name);st=path.lstat()
        check(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==0 and st.st_gid==0 and stat.S_IMODE(st.st_mode)==pin['mode'],'INSTALLED_FILE_AUTHORITY')
        check(digest(path.read_bytes())==pin['sha256'],'INSTALLED_FILE_CHANGED')


def install(upgrade=False,production_dns=False,preserve_assets=False,release_profile=False):
    check(MANIFEST.exists()==upgrade,'INSTALL_STATE')
    quiescent()
    from scripts.m4_production_dns import prerequisites,retire_legacy_units,SCRIPT
    if upgrade and SCRIPT in json.loads(MANIFEST.read_text())["files"]:production_dns=True
    if production_dns:prerequisites()
    files=payload(production_dns,release_profile) # validate everything before filesystem changes
    old=None
    if upgrade:
        old=json.loads(MANIFEST.read_text())
        verify_installed(old)
    if preserve_assets:
        for name in list(files):
            path=Path(name)
            if name.startswith('/opt/bridge-official/assets/') and path.exists():
                st=path.lstat()
                check(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_gid==0 and st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o444,'ASSET_AUTHORITY')
                files[name]=(path.read_bytes(),0o444)
    retire_legacy_units()
    uid,gid=account('independent-bridge');daed_uid,daed_gid=account('bridge-daed')
    for path,mode,u,g in [('/etc/daed-independent-bridge',0o755,0,0),('/opt/bridge',0o755,0,0),('/opt/bridge-official',0o755,0,0),('/opt/bridge-service',0o755,0,0),(str(BASE),0o711,0,0),(str(BASE/'versions'),0o700,0,0),(str(BASE/'inbox'),0o700,uid,gid),('/var/lib/bridge-m4-client',0o700,uid,gid),('/var/lib/bridge-m4-client/extensions',0o700,uid,gid),('/var/lib/bridge-m4-attestation',0o750,0,gid),('/var/lib/bridge-daed',0o700,daed_uid,daed_gid)]:folder(path,mode,u,g)
    # No overwrite of an unmanaged unit/binary on a first install.
    for name in files:
        check(not Path(name).exists() or (old is not None and name in old['files']) or (preserve_assets and name.startswith('/opt/bridge-official/assets/')),'UNMANAGED_INSTALL_FILE')
    from scripts.m4_install_transaction import begin,commit,write
    begin(set(files)|(set(old['files']) if old else set()))
    for name,(body,mode) in files.items():
        if old and old['files'].get(name)=={'sha256':digest(body),'mode':mode}:continue
        path=Path(name)
        missing=[];parent=path.parent
        while not parent.exists():missing.append(parent);parent=parent.parent
        for p in reversed(missing):folder(p,0o755)
        check(not path.is_symlink(),'INSTALL_LINK')
        write(path,body,mode)
    if old:
        for name in set(old['files'])-set(files):Path(name).unlink()
    (BASE/'apply.lock').touch(mode=0o600,exist_ok=True)
    ctl('daemon-reload')
    sys.path.insert(0,'/opt/bridge')
    from bridge_m2.unit_identity import snapshot
    from bridge_m2.control import ENV
    from bridge_m2.security import atomic_json
    pin=digest(files['/opt/bridge-service/dae'][0])
    p={'bridgeUid':uid,'bridgeGid':gid,'serviceBinarySha256':pin,'validateBinarySha256':pin,'serviceIdentity':snapshot(ENV)}
    atomic_json(BASE/'policy.json',p)
    record={'schemaVersion':1,'files':{n:{'sha256':digest(b),'mode':m} for n,(b,m) in sorted(files.items())}}
    write(MANIFEST,(json.dumps(record,sort_keys=True)+'\n').encode(),0o644)
    subprocess.run(['/usr/bin/systemd-tmpfiles','--create','/etc/tmpfiles.d/bridge-m4.conf'],check=True)
    commit()
    print(json.dumps({'installed':True,'servicesStarted':False,'fileCount':len(files)}))

def uninstall(preserve_assets=False):
    quiescent();record=json.loads(MANIFEST.read_text())
    # Verify all bytes first; do not partially remove a modified installation.
    verify_installed(record)
    from scripts.m4_production_dns import retire_legacy_units
    retire_legacy_units()
    for name in record['files']:
        if name.startswith('/etc/systemd/system/') and name.endswith(('.service','.socket','.timer')):
            ctl('disable',Path(name).name)
    from scripts.m4_install_transaction import begin,commit
    begin(record['files'])
    for name in record['files']:
        if not (preserve_assets and name.startswith('/opt/bridge-official/assets/')):Path(name).unlink()
    MANIFEST.unlink();ctl('daemon-reload');commit()
    print('{"uninstalled":true,"stateAndDatabasesRetained":true}')

def main():
    check(os.geteuid()==0 and Path('/run/systemd/system').is_dir(),'DEBIAN_SYSTEMD_ROOT_REQUIRED')
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('install','upgrade','uninstall','recover'));parser.add_argument('--production-dns',action='store_true');args=parser.parse_args()
    from scripts.m4_install_transaction import exclusive
    with exclusive():
        if args.action=='recover':
            quiescent()
            from scripts.m4_install_transaction import restore
            restore();ctl('daemon-reload');print('{"restored":true,"servicesStarted":false}')
        elif args.action=='uninstall':uninstall()
        else:install(args.action=='upgrade',args.production_dns)

if __name__=='__main__':main()
