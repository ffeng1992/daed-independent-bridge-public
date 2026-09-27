"""Populate only hash-locked release dependencies; support prefilled offline caches."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile


def need(ok, code):
    if not ok: raise RuntimeError(code)


def verify_archive(raw, pin):
    need(hashlib.sha256(raw).hexdigest() == pin['sha256'], 'OFFICIAL_ARCHIVE_HASH')
    expected = {m['path']: m for m in pin['archive_members']}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        need(len(members) == len(expected) and {m.filename for m in members} == set(expected), 'OFFICIAL_MEMBER_SET')
        files = {}
        for m in members:
            body = z.read(m); p = expected[m.filename]
            need(len(body) == p['size'] and hashlib.sha256(body).hexdigest() == p['sha256'], 'OFFICIAL_MEMBER_HASH')
            files[m.filename] = body
        return files


def prepare(root):
    root = Path(root)
    from scripts.release_frontend import prepare as prepare_frontend
    prepare_frontend(root)
    pins = json.loads((root / 'upstream.lock.json').read_text())['components']
    (root / 'official').mkdir(exist_ok=True)
    (root / 'out/m2-official').mkdir(parents=True, exist_ok=True)
    for name, pin in pins.items():
        cached = root / 'official' / (name + '.zip')
        raw = cached.read_bytes() if cached.exists() else urllib.request.urlopen(pin['url'], timeout=90).read(150*1024*1024)
        files = verify_archive(raw, pin)
        if not cached.exists(): cached.write_bytes(raw)
        executable = next(p for p in files if p.endswith(name+'-linux-x86_64'))
        dest = root / 'out/m2-official' / name
        if not dest.exists() or dest.read_bytes() != files[executable]:
            dest.write_bytes(files[executable]); dest.chmod(0o555)
    from scripts.m4_package import wheels_payload
    wheels = root / 'out/m4-wheels'; wheels.mkdir(parents=True, exist_ok=True)
    lock = root / 'deployment/m4/requirements.lock'
    if not list(wheels.glob('*.whl')):
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--require-hashes', '--no-deps',
                        '--only-binary=:all:', '-r', str(lock), '--dest', str(wheels)],
                       check=True, capture_output=True, timeout=300)
    payload = wheels_payload(lock.read_text(), {p.name:p.read_bytes() for p in wheels.glob('*.whl')})
    vendor = root / 'out/m4-vendor'; vendor.mkdir(exist_ok=True)
    for name, body in payload.items():
        dest = vendor / name; dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_bytes() != body: dest.write_bytes(body)
    actual = {p.relative_to(vendor).as_posix() for p in vendor.rglob('*') if p.is_file()}
    need(actual == set(payload), 'DEPENDENCY_FILE_SET')
    sys.path.insert(0, str(vendor))
