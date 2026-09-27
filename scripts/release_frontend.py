"""Fetch the unmodified official static build, validating archive and every file."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request


def need(ok, code):
    if not ok:raise RuntimeError(code)


def unpack(raw, pin):
    need(hashlib.sha256(raw).hexdigest()==pin['sha256'],'DAED_WEB_ARCHIVE_HASH')
    expected={m['path']:m for m in pin['files']};files={}
    need(len(expected)==len(pin['files']),'DAED_WEB_LOCK_DUPLICATE')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        for member in archive:
            need(member.isdir() or member.isfile(),'DAED_WEB_SPECIAL_MEMBER')
            if member.isdir():continue
            need(member.name.startswith(pin['archivePrefix']),'DAED_WEB_PREFIX')
            name=member.name[len(pin['archivePrefix']):];path=PurePosixPath(name)
            need(not path.is_absolute() and '..' not in path.parts and '\\' not in name and
                 name in expected and name not in files,'DAED_WEB_MEMBER_SET')
            body=archive.extractfile(member).read();item=expected[name]
            need(len(body)==item['size'] and hashlib.sha256(body).hexdigest()==item['sha256'],'DAED_WEB_MEMBER_HASH')
            files[name]=body
    need(set(files)==set(expected),'DAED_WEB_MEMBER_SET')
    return files


def prepare(root):
    root=Path(root);pin=json.loads((root/'upstream.lock.json').read_text())['webFrontend']
    directory=root/'official';directory.mkdir(exist_ok=True)
    for name,url,sha in (('daed-web.tar.gz',pin['url'],pin['sha256']),
                         ('daed-web-LICENSE',pin['license']['url'],pin['license']['sha256'])):
        target=directory/name
        raw=target.read_bytes() if target.exists() else urllib.request.urlopen(url,timeout=120).read(64*1024*1024)
        need(hashlib.sha256(raw).hexdigest()==sha,'DAED_WEB_DOWNLOAD_HASH')
        if name.endswith('.tar.gz'):unpack(raw,pin)
        if not target.exists():target.write_bytes(raw)


def payload(root):
    root=Path(root);pin=json.loads((root/'upstream.lock.json').read_text())['webFrontend']
    files=unpack((root/'official/daed-web.tar.gz').read_bytes(),pin)
    license=(root/'official/daed-web-LICENSE').read_bytes()
    need(hashlib.sha256(license).hexdigest()==pin['license']['sha256'],'DAED_WEB_LICENSE_HASH')
    result={'/opt/bridge-daed-web/'+n:(b,0o444) for n,b in files.items()}
    result['/opt/bridge-daed-web/LICENSE']=(license,0o444)
    result['/usr/local/bin/bridge-daed-web']=(b'import sys\nsys.dont_write_bytecode=True\nsys.path.insert(0,"/opt/bridge")\nfrom bridge_m4.official_web import main\nmain()\n',0o755)
    return result
