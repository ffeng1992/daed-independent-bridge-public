"""A fresh namespace for each matrix run, bound to source, lock and boot.

Historical evidence is retained but never implicitly reused by another run.
No service operation, network request or production path is used by this module.
"""
import hashlib
import contextlib
import fcntl
import json
import os
import stat
from pathlib import Path
import sys
import uuid

SOURCE = Path(__file__).resolve().parents[2]
EVIDENCE = Path('/evidence')
# Source inputs that affect packaging, deployment, fixtures and acceptance.
# Generated output, downloaded official assets and VCS metadata are excluded;
# their locked identities remain source inputs, not mutable test output.
PREFIXES = ('bridge_m1', 'bridge_m2', 'bridge_m3', 'bridge_m4', 'contracts',
            'scripts', 'integration', 'fixtures', 'deployment', 'tests',
            'packaging', '.github')
ROOT_INPUTS = ('upstream.lock.json', 'container.lock.json', 'requirements-dev.txt',
               'requirements-linux.lock', 'VERSION', '.dockerignore',
               'Dockerfile', 'pyproject.toml', 'package.json', 'package-lock.json')
SOURCE_SUFFIXES = {'.sh', '.py', '.js', '.cjs', '.mjs'}
FINGERPRINT_VERSION = 2
SOURCE_LIMIT = 32 * 1024 * 1024


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def _source_pin(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= SOURCE_LIMIT,
                'MATRIX_SOURCE_FILE')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(SOURCE_LIMIT + 1)
        after = os.fstat(fd)
        linked = path.lstat()
        signature = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns, x.st_mode)
        require(signature(before) == signature(after) == signature(linked) and
                len(raw) == before.st_size, 'MATRIX_SOURCE_CHANGED')
        return {'sha256': sha(raw), 'size': len(raw), 'mode': stat.S_IMODE(before.st_mode)}
    finally:
        os.close(fd)


def fingerprint(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'MATRIX_SOURCE_ROOT')
    files = {}
    for name in PREFIXES:
        folder = root / name
        require(not folder.is_symlink(), 'MATRIX_SOURCE_LINK')
        if not folder.exists():
            continue
        require(folder.is_dir(), 'MATRIX_SOURCE_DIRECTORY')
        for path in sorted(folder.rglob('*')):
            if '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}:
                continue
            require(not path.is_symlink(), 'MATRIX_SOURCE_LINK')
            if path.is_dir():
                continue
            files[path.relative_to(root).as_posix()] = _source_pin(path)
    inputs = set(ROOT_INPUTS) | {p.name for p in root.iterdir() if p.suffix in SOURCE_SUFFIXES}
    require((root / 'upstream.lock.json').is_file(), 'MATRIX_UPSTREAM_LOCK_MISSING')
    for name in sorted(inputs):
        path = root / name
        require(not path.is_symlink(), 'MATRIX_SOURCE_LINK')
        if path.exists():
            files[name] = _source_pin(path)
    return sha(json.dumps({'fingerprintVersion': FINGERPRINT_VERSION, 'files': files},
                         sort_keys=True, separators=(',', ':')).encode())


def _boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def _start_run_unlocked(root=SOURCE, evidence=EVIDENCE, *, boot=None):
    evidence = Path(evidence)
    require(evidence.is_dir() and not evidence.is_symlink(), 'MATRIX_EVIDENCE_ROOT')
    run_id = uuid.uuid4().hex
    runs = evidence / 'runs'
    require(not runs.is_symlink(), 'MATRIX_EVIDENCE_LINK')
    runs.mkdir(mode=0o700, exist_ok=True)
    directory = runs / run_id
    directory.mkdir(mode=0o700)
    value = {'schemaVersion': 2, 'fingerprintVersion': FINGERPRINT_VERSION, 'runId': run_id, 'sourceTreeSha256': fingerprint(root),
             'bootId': _boot() if boot is None else boot, 'pythonOptimize': sys.flags.optimize}
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    (directory / 'scope.json').write_bytes(raw)
    temp = evidence / ('.matrix-run-' + run_id)
    try:
        with temp.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, evidence / 'matrix-run.json')
    finally:
        temp.unlink(missing_ok=True)
    return value


def current(root=SOURCE, evidence=EVIDENCE, *, boot=None):
    evidence = Path(evidence)
    path = evidence / 'matrix-run.json'
    require(path.is_file() and not path.is_symlink(), 'MATRIX_RUN_NOT_INITIALIZED')
    value = json.loads(path.read_text())
    require(type(value) is dict and set(value) ==
        {'schemaVersion','fingerprintVersion','runId','sourceTreeSha256','bootId','pythonOptimize'} and
        type(value['schemaVersion']) is int and value['schemaVersion'] == 2 and
        type(value['fingerprintVersion']) is int and value['fingerprintVersion'] == FINGERPRINT_VERSION and
        type(value['runId']) is str and len(value['runId']) == 32 and
        all(c in '0123456789abcdef' for c in value['runId']) and
        type(value['bootId']) is str and bool(value['bootId']) and
        type(value['pythonOptimize']) is int and value['pythonOptimize'] in (0, 1, 2), 'MATRIX_RUN_SCHEMA')
    expected = os.environ.get('BRIDGE_MATRIX_RUN_ID')
    require(expected is None or value['runId'] == expected, 'MATRIX_RUN_REPLACED')
    require(value['sourceTreeSha256'] == fingerprint(root) and
            value['bootId'] == (_boot() if boot is None else boot) and
            value['pythonOptimize'] == sys.flags.optimize, 'MATRIX_RUN_CONTEXT_CHANGED')
    folder = evidence / 'runs' / value['runId']
    require(folder.is_dir() and not folder.is_symlink() and
            not (folder / 'scope.json').is_symlink() and
            json.loads((folder / 'scope.json').read_text()) == value, 'MATRIX_RUN_BINDING')
    return value, folder


def scope_file(path, *, root=SOURCE, evidence=EVIDENCE, boot=None):
    path, evidence = Path(path), Path(evidence)
    relative = path.relative_to(evidence)
    require('..' not in relative.parts and (not relative.parts or relative.parts[0] != 'runs'), 'MATRIX_EVIDENCE_PATH')
    value, folder = current(root, evidence, boot=boot)
    if boot is None:
        require(os.environ.get('BRIDGE_MATRIX_RUN_ID') == value['runId'],
                'MATRIX_RUN_ID_REQUIRED_USE_LAUNCHER')
    return folder if not relative.parts else evidence_path(folder, relative.as_posix())


def evidence_path(folder, name):
    """A ledger entry cannot escape its selected run directory, even by symlink."""
    relative = Path(name)
    require(type(name) is str and bool(name) and not relative.is_absolute() and
            '..' not in relative.parts and '\\' not in name, 'MATRIX_EVIDENCE_PATH')
    folder = Path(folder)
    require(folder.is_dir() and not folder.is_symlink(), 'MATRIX_EVIDENCE_ROOT')
    path = folder
    for part in relative.parts:
        path = path / part
        require(not path.is_symlink(), 'MATRIX_EVIDENCE_LINK')
    return path


def report_scope(folder, *, source=SOURCE):
    """Verify an explicitly selected saved run for OFFLINE report generation.

    The recorded boot/interpreter describe the test run, not the reporting host.
    No claim of a still-running VM or actual runtime test success is made here.
    """
    folder = Path(folder)
    path = evidence_path(folder, 'scope.json')
    raw = path.read_bytes()
    require(len(raw) <= 4096, 'MATRIX_RUN_SCHEMA')
    value = json.loads(raw)
    require(type(value) is dict and set(value) ==
            {'schemaVersion','fingerprintVersion','runId','sourceTreeSha256','bootId','pythonOptimize'},
            'MATRIX_RUN_SCHEMA')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 2 and
            type(value['fingerprintVersion']) is int and value['fingerprintVersion'] == FINGERPRINT_VERSION and
            type(value['runId']) is str and len(value['runId']) == 32 and
            all(c in '0123456789abcdef' for c in value['runId']) and
            folder.name == value['runId'] and folder.parent.name == 'runs' and
            type(value['bootId']) is str and bool(value['bootId']) and
            type(value['pythonOptimize']) is int and value['pythonOptimize'] in (0, 1, 2),
            'MATRIX_RUN_SCHEMA')
    require(value['sourceTreeSha256'] == fingerprint(source), 'MATRIX_REPORT_SOURCE_CHANGED')
    return value


@contextlib.contextmanager
def run_lock(evidence=EVIDENCE, *, exclusive=False):
    """A launcher holds SH for the whole child lifetime; initialization needs EX."""
    evidence = Path(evidence)
    require(evidence.is_dir() and not evidence.is_symlink(), 'MATRIX_EVIDENCE_ROOT')
    fd = os.open(evidence / '.matrix-run.lock',
                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and
                st.st_uid == os.geteuid() and not st.st_mode & 0o077,
                'MATRIX_RUN_LOCK_IDENTITY')
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('MATRIX_RUN_BUSY') from None
        yield
    finally:
        os.close(fd)


def start_run(root=SOURCE, evidence=EVIDENCE, *, boot=None):
    with run_lock(evidence, exclusive=True):
        return _start_run_unlocked(root, evidence, boot=boot)
