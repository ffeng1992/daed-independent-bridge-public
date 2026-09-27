"""Build/verify an offline deployment directory, never a review archive."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PREFIXES=('bridge_m1/','bridge_m2/','bridge_m4/','contracts/','queries/','deployment/m4/')
SCRIPTS={'scripts/m4_production_dns.py','scripts/__init__.py','scripts/m4_install.py','scripts/m4_install_transaction.py','scripts/m4_assets.py','scripts/m4_package.py'}

def need(ok,code):
    if not ok:raise RuntimeError(code)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def name_ok(name):
    p=PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and str(p)==name and '\\' not in name

def wheels_payload(lock,wheels):
    expected={}
    for line in lock.splitlines():
        if not line.strip() or line.startswith('#'):continue
        match=re.fullmatch(r'([A-Za-z0-9_]+)==([A-Za-z0-9.]+) --hash=sha256:([a-f0-9]{64})',line)
        need(match is not None,'DEPENDENCY_LOCK_SCHEMA')
        key=match[1]+'-'+match[2]+'-';need(key not in expected,'DEPENDENCY_DUPLICATE');expected[key]=match[3]
    need(len(wheels)==len(expected),'DEPENDENCY_SET')
    files={};seen=set()
    for name,raw in sorted(wheels.items()):
        keys=[k for k in expected if name.startswith(k) and name.endswith('.whl')]
        need(len(keys)==1 and keys[0] not in seen,'DEPENDENCY_SET');key=keys[0];seen.add(key)
        need(digest(raw)==expected[key],'DEPENDENCY_HASH')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members=archive.infolist();names=[m.filename for m in members]
            need(len(names)==len(set(names)),'DEPENDENCY_DUPLICATE_MEMBER')
            for member in members:
                if member.is_dir():continue
                name=member.filename
                need(name_ok(name) and not stat.S_ISLNK(member.external_attr>>16),'DEPENDENCY_MEMBER')
                need(not any(part.endswith('.data') for part in PurePosixPath(name).parts) and name not in files,'DEPENDENCY_COLLISION')
                files[name]=archive.read(member)
    need(seen==set(expected),'DEPENDENCY_SET')
    return files

def verify(root,expected_hash,*,root_owned=False):
    root=Path(root);need(root.is_dir() and not root.is_symlink(),'PACKAGE_DIRECTORY')
    need(bool(re.fullmatch('[a-f0-9]{64}',expected_hash)),'PACKAGE_EXPECTED_HASH')
    manifest=root/'deployment-manifest.json'
    need(manifest.is_file() and not manifest.is_symlink(),'PACKAGE_MANIFEST')
    raw=manifest.read_bytes();need(digest(raw)==expected_hash,'PACKAGE_MANIFEST_HASH')
    value=json.loads(raw);need(set(value)=={'schemaVersion','checkoutSha','files'} and value['schemaVersion']==1,'PACKAGE_SCHEMA')
    need(bool(re.fullmatch('[a-f0-9]{40}',value['checkoutSha'])) and type(value['files']) is dict,'PACKAGE_SCHEMA')
    actual=set()
    for path in root.rglob('*'):
        st=path.lstat();need(not stat.S_ISLNK(st.st_mode),'PACKAGE_LINK')
        if root_owned:need(st.st_uid==0 and not st.st_mode&0o022,'PACKAGE_AUTHORITY')
        if path.is_dir():continue
        relative=path.relative_to(root).as_posix()
        need(stat.S_ISREG(st.st_mode) and st.st_nlink==1,'PACKAGE_FILE_TYPE')
        if relative=='deployment-manifest.json':continue
        actual.add(relative)
        need(relative in value['files'] and name_ok(relative),'PACKAGE_FILE_SET')
        need(st.st_mode&0o222==0,'PACKAGE_WRITABLE_FILE')
        need(digest(path.read_bytes())==value['files'][relative],'PACKAGE_FILE_HASH')
    need(actual==set(value['files']),'PACKAGE_FILE_SET')
    return value

def build():
    # Read committed bytes only. Neither local inputs nor untracked files enter it.
    subprocess.run(['git','diff','--exit-code'],cwd=ROOT,check=True)
    subprocess.run(['git','diff','--cached','--exit-code'],cwd=ROOT,check=True)
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',sha],cwd=ROOT,text=True).splitlines()
    files={n:subprocess.check_output(['git','show',sha+':'+n],cwd=ROOT) for n in names if n.startswith(PREFIXES) or n in SCRIPTS or n=='upstream.lock.json'}
    lock=files['deployment/m4/requirements.lock'].decode()
    wheels={p.name:p.read_bytes() for p in (ROOT/'out/m4-wheels').glob('*.whl')}
    files.update({'out/m4-vendor/'+n:b for n,b in wheels_payload(lock,wheels).items()})
    for name in ('dae','daed'):files['out/m2-official/'+name]=(ROOT/'out/m2-official'/name).read_bytes()
    files['official/dae.zip']=(ROOT/'out/m4-assets/dae.zip').read_bytes()
    # Check release archive/members and binary hashes before emitting a package.
    upstream=json.loads(files['upstream.lock.json'])
    from scripts.m4_assets import official_assets
    official_assets(files['official/dae.zip'],upstream['components']['dae'])
    for name in ('dae','daed'):
        member=next(m for m in upstream['components'][name]['archive_members'] if m['path'].endswith(name+'-linux-x86_64'))
        need(digest(files['out/m2-official/'+name])==member['sha256'],'OFFICIAL_BINARY_HASH')
    files['install.py']=b'''import os,sys
from pathlib import Path
sys.dont_write_bytecode=True
r=Path(__file__).resolve().parent
if os.geteuid()!=0:raise SystemExit('ROOT_REQUIRED')
for p in (r,*r.parents):
 s=p.stat()
 if s.st_uid!=0 or s.st_mode&0o022:raise SystemExit('ROOT_OWNED_STAGING_REQUIRED')
sys.path[:0]=[str(r),str(r/"out/m4-vendor")]
from scripts.m4_package import verify
if len(sys.argv) not in (3,4) or (len(sys.argv)==4 and sys.argv[3]!='--production-dns'):raise SystemExit('expected manifest SHA-256, action, optional --production-dns')
verify(r,sys.argv.pop(1),root_owned=True)
from scripts.m4_install import main
main()
'''

    target=ROOT/'out'/('m4-deployment-'+sha);need(not target.exists(),'PACKAGE_ALREADY_EXISTS');target.mkdir(mode=0o755)
    for name,body in sorted(files.items()):
        need(name_ok(name),'PACKAGE_PATH');path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body);path.chmod(0o444)
    raw=(json.dumps({'schemaVersion':1,'checkoutSha':sha,'files':{n:digest(b) for n,b in sorted(files.items())}},sort_keys=True,separators=(',',':'))+'\n').encode()
    manifest=target/'deployment-manifest.json';manifest.write_bytes(raw);manifest.chmod(0o444)
    for path in sorted((p for p in target.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):path.chmod(0o555)
    target.chmod(0o555);verify(target,digest(raw))
    print(json.dumps({'directory':str(target),'checkoutSha':sha,'manifestSha256':digest(raw),'fileCount':len(files),'archiveCreated':False}))

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True);s.add_parser('build');v=s.add_parser('verify');v.add_argument('directory');v.add_argument('--manifest-sha256',required=True);a=p.parse_args()
    if a.action=='build':build()
    else:verify(a.directory,a.manifest_sha256);print('{"verified":true}')
if __name__=='__main__':main()
