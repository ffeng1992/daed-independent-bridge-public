"""Export only audited committed files. No worktree bytes or history are copied."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def need(ok, code):
    if not ok:raise RuntimeError(code)

def encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()

def scan(name, body):
    path=PurePosixPath(name)
    need(not path.is_absolute() and '..' not in path.parts and '\\' not in name,'PUBLIC_PATH')
    need(not any(x in path.parts for x in ('.local','out','official','.git','__pycache__')),'PUBLIC_PRIVATE_FILE')
    need(path.suffix.lower() not in {'.sqlite','.db','.pem','.key','.log','.zip','.pyc','.qcow2'},'PUBLIC_PRIVATE_FILE')
    need(not re.search(r'(?i)(primary[_-]rollback|failure[_-]capsule|initial-admin)',name),'PUBLIC_INTERNAL_FILE')
    text=body.decode('utf-8')
    patterns=(r'/(?:Users|Volumes|home)/[^\s\"\']+',r'[A-Z]:[\\/]Users[\\/]',
              r'(?i)(?:daed[-_]shanghai|shanghai[-_](?:prod|daed)|\u4e0a\u6d77)',
              r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
              r'gh[pousr]_[A-Za-z0-9]{30,}',r'github_pat_[A-Za-z0-9_]{30,}',
              r'AKIA[A-Z0-9]{16}')
    for pattern in patterns:
        need(not re.search(pattern,text),'PUBLIC_FORBIDDEN_CONTENT:'+name)
    for token in re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])',text):
        try:address=ipaddress.IPv4Address(token)
        except ValueError:continue
        sensitive=((167772160,8),(2886729728,12),(3232235520,16),(1681915904,10))
        # Documentation/test ranges and loopback are permitted; private site IPs are not.
        need(not any(address in ipaddress.ip_network(n) for n in sensitive),'PUBLIC_SITE_IP:'+name)

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)

def files_at(ref):
    sha=git('rev-parse',ref+'^{commit}').decode().strip()
    allowed=json.loads(git('show',sha+':scripts/public-allowlist.json'))
    need(type(allowed) is list and allowed==sorted(set(allowed)),'PUBLIC_ALLOWLIST_SCHEMA')
    tree={}
    for record in git('ls-tree','-rz',sha).split(b'\0'):
        if not record:continue
        meta,name=record.split(b'\t',1);mode,kind,oid=meta.decode().split()
        tree[name.decode()]=(mode,kind,oid)
    files={}
    for name in allowed:
        need(name in tree,'PUBLIC_MISSING_SOURCE:'+name)
        mode,kind,oid=tree[name]
        need(kind=='blob' and mode in ('100644','100755'),'PUBLIC_SPECIAL_FILE:'+name)
        body=git('cat-file','blob',oid);scan(name,body)
        files[name]=(int(mode[-3:],8),body)
    return sha,files

def metadata(sha,files):
    hashes={n:{'mode':mode,'sha256':hashlib.sha256(body).hexdigest()} for n,(mode,body) in sorted(files.items())}
    return encoded({'schemaVersion':1,'sourceCommit':sha,'version':files['VERSION'][1].decode().strip(),
                    'treeSha256':hashlib.sha256(encoded(hashes)).hexdigest(),'files':hashes})

def export(ref,output):
    sha,files=files_at(ref)
    output=Path(output).absolute()
    need(not output.exists() and not output.is_symlink(),'PUBLIC_OUTPUT_MUST_NOT_EXIST')
    # Scan the complete tree before creating any output.
    proof=metadata(sha,files)
    output.mkdir(parents=True)
    for name,(mode,body) in sorted(files.items()):
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(body);target.chmod(mode)
    (output/'.public-source.json').write_bytes(proof)
    return json.loads(proof)

def verify(root):
    root=Path(root);proof=json.loads((root/'.public-source.json').read_bytes())
    names=set()
    for p in root.rglob('*'):
        relative=p.relative_to(root)
        if relative.parts[0]=='.git':continue
        need(not p.is_symlink(),'PUBLIC_LINK')
        if not p.is_file():continue
        if str(relative)=='.public-source.json':continue
        names.add(relative.as_posix())
    need(names==set(proof['files']),'PUBLIC_TREE_FILE_SET')
    for name,item in proof['files'].items():
        p=root/name;body=p.read_bytes();scan(name,body)
        need(hashlib.sha256(body).hexdigest()==item['sha256'] and p.stat().st_mode&0o777==item['mode'],'PUBLIC_TREE_CHANGED:'+name)
    need(hashlib.sha256(encoded(proof['files'])).hexdigest()==proof['treeSha256'],'PUBLIC_TREE_HASH')
    return proof

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref',default='main');parser.add_argument('--output',type=Path)
    parser.add_argument('--verify',type=Path)
    args=parser.parse_args()
    if args.verify:
        need(args.output is None,'PUBLIC_ARGUMENTS');result=verify(args.verify)
    else:
        need(args.output is not None,'PUBLIC_OUTPUT_REQUIRED');result=export(args.ref,args.output)
    print(json.dumps({k:result[k] for k in ('sourceCommit','version','treeSha256')}))
if __name__=='__main__':main()
