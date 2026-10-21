"""Verified, immutable geodata generations, independent of pinned official DAE assets.

Original DAE archive members and upstream.lock.json are never rewritten.
A single atomic relative symlink selects complete, hash-bound generations.
"""
import hashlib
import json
import os
import re
import stat
from pathlib import Path

BASE = Path('/var/lib/daed-independent-bridge/geodata')
OFFICIAL = Path('/opt/bridge-official/assets')
DATASETS = ('geosite.dat', 'geoip.dat')
HEX = re.compile(r'[a-f0-9]{64}\Z')
LIMITS = {'geosite.dat': 20 * 1024 * 1024, 'geoip.dat': 80 * 1024 * 1024}


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode()


def verify_file(path, digest=None, *, uid=0, max_size=None):
    path = Path(path)
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == uid and
            (st.st_mode & 0o022) == 0 and st.st_size > 0, 'GEODATA_FILE_AUTHORITY')
    if max_size is not None:
        require(st.st_size <= max_size, 'GEODATA_SIZE_LIMIT')
    raw = path.read_bytes()
    require(len(raw) == st.st_size, 'GEODATA_READ_SIZE')
    if digest is not None:
        require(sha(raw) == digest, 'GEODATA_FILE_HASH')
    return raw


def check_directory(path, uid=0):
    st = Path(path).lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == uid and not (st.st_mode & 0o022),
            'GEODATA_DIRECTORY_AUTHORITY')


def verify_generation_folder(folder, *, uid=0):
    """Verify a published generation even before current points to it."""
    folder = Path(folder)
    require(HEX.fullmatch(folder.name) is not None and
            folder.parent.name == 'versions' and folder.is_absolute(),
            'GEODATA_GENERATION_PATH')
    check_directory(folder, uid)
    raw = verify_file(folder / 'manifest.json', uid=uid, max_size=4096)
    require(sha(raw) == folder.name, 'GEODATA_MANIFEST_ID')
    item = json.loads(raw)
    require(type(item) is dict and set(item) == {'schemaVersion', 'datasets'} and
            type(item['schemaVersion']) is int and item['schemaVersion'] == 1 and
            type(item['datasets']) is dict and set(item['datasets']) == set(DATASETS),
            'GEODATA_MANIFEST_SCHEMA')
    for name in DATASETS:
        entry = item['datasets'][name]
        require(type(entry) is dict and set(entry) == {'sha256', 'size', 'repository', 'tag'} and
                isinstance(entry['sha256'], str) and HEX.fullmatch(entry['sha256']) is not None and
                type(entry['size']) is int and 0 < entry['size'] <= LIMITS[name] and
                type(entry['repository']) is str and type(entry['tag']) is str,
                'GEODATA_DATASET_SCHEMA')
        expect = 'v2fly/domain-list-community' if name == 'geosite.dat' else 'v2fly/geoip'
        require(entry['repository'] == expect and 0 < len(entry['tag']) <= 70,
                'GEODATA_SOURCE_IDENTITY')
        payload = verify_file(folder / name, entry['sha256'], uid=uid, max_size=LIMITS[name])
        require(len(payload) == entry['size'], 'GEODATA_DATASET_SIZE')
    return folder, item


def generation(root=BASE, *, uid=0):
    """Return (verified path, manifest), or (None,None) for existing pinned data."""
    root = Path(root)
    pointer = root / 'current'
    if not pointer.is_symlink():
        require(not pointer.exists(), 'GEODATA_POINTER_TYPE')
        return None, None
    check_directory(root, uid)
    target = os.readlink(pointer)
    require(re.fullmatch(r'versions/[a-f0-9]{64}', target) is not None,
            'GEODATA_POINTER_TARGET')
    return verify_generation_folder(root / target, uid=uid)


def selected_dir(root=BASE, official=OFFICIAL, *, uid=0):
    folder, _ = generation(root, uid=uid)
    return folder if folder is not None else Path(official)


def selected_hashes(root=BASE, official=OFFICIAL, *, uid=0):
    folder = selected_dir(root, official, uid=uid)
    return {name: sha(verify_file(folder / name, uid=uid, max_size=LIMITS[name]))
            for name in DATASETS}


def syncdir(folder):
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_bytes(path, raw, mode=0o600):
    path = Path(path)
    stage = path.with_name('.' + path.name + '.tmp.' + str(os.getpid()))
    descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(stage, mode)
        os.replace(stage, path)
        syncdir(path.parent)
    finally:
        stage.unlink(missing_ok=True)


def switch(root, identity, *, uid=0):
    """Point to an already published complete verified generation."""
    root = Path(root)
    current = root / 'current'
    if identity is not None:
        require(isinstance(identity, str) and HEX.fullmatch(identity) is not None,
                'GEODATA_SWITCH_ID')
        check_directory(root / 'versions' / identity, uid)
        next_link = root / ('current.next.' + str(os.getpid()))
        try:
            os.symlink('versions/' + identity, next_link)
            os.replace(next_link, current)
        finally:
            next_link.unlink(missing_ok=True)
    else:
        if current.is_symlink():
            current.unlink()
        else:
            require(not current.exists(), 'GEODATA_POINTER_TYPE')
    syncdir(root)


def current_id(root=BASE):
    pointer = Path(root) / 'current'
    if not pointer.is_symlink():
        require(not pointer.exists(), 'GEODATA_POINTER_TYPE')
        return None
    target = os.readlink(pointer)
    require(re.fullmatch(r'versions/[a-f0-9]{64}', target) is not None,
            'GEODATA_POINTER_TARGET')
    return target.split('/')[1]
