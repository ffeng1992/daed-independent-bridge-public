"""Serialize test evidence across fixture processes and the JSON reader.

The evidence directory may be a VM shared filesystem where append is not
atomic between processes. The lock is on the guest's local runtime filesystem.
Malformed evidence remains an error; no partial records are skipped.
"""
from integration.ui_matrix.evidence_scope import scope_file
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import threading
import os
import sys
from integration.ui_matrix.evidence_scope import evidence_path

LOG = Path('/evidence/path-events.jsonl')
LOCK_PATH = Path('/run/matrix-path-events.lock')
THREAD_LOCK = threading.Lock()


class FixtureEvidence:
    """Bind once outside the measured path; launcher checks full source at both ends.

    Every event still checks immutable run/boot/interpreter and safe paths. This
    does not replace the launcher's full before/after source verification.
    """
    def __init__(self):
        self.folder = scope_file(Path('/evidence'))
        self.marker = Path('/evidence/matrix-run.json')
        self.raw = self.marker.read_bytes()
        self.boot = Path('/proc/sys/kernel/random/boot_id').read_bytes()
        self.run = json.loads(self.raw)['runId']
        self.optimize = sys.flags.optimize

    def path(self, name):
        if (self.marker.is_symlink() or self.marker.read_bytes() != self.raw or
            Path('/proc/sys/kernel/random/boot_id').read_bytes() != self.boot or
            os.environ.get('BRIDGE_MATRIX_RUN_ID') != self.run or
            sys.flags.optimize != self.optimize or
            (self.folder/'scope.json').is_symlink() or
            (self.folder/'scope.json').read_bytes() != self.raw):
            raise RuntimeError('MATRIX_RUN_CONTEXT_CHANGED')
        return evidence_path(self.folder, name)


@contextmanager
def locked(lock_path=LOCK_PATH, shared=False):
    with THREAD_LOCK, lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def append(value, path=None, lock_path=LOCK_PATH):
    path = scope_file(LOG) if path is None else path
    with locked(lock_path), path.open('a') as stream:
        stream.write(json.dumps(value) + '\n')


def read(path=None, lock_path=LOCK_PATH):
    path = scope_file(LOG) if path is None else path
    with locked(lock_path, shared=True):
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
