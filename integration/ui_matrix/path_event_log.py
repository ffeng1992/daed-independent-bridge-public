"""Serialize test evidence across fixture processes and the JSON reader.

The evidence directory may be a VM shared filesystem where append is not
atomic between processes. The lock is on the guest's local runtime filesystem.
Malformed evidence remains an error; no partial records are skipped.
"""
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import threading

LOG = Path('/evidence/path-events.jsonl')
LOCK_PATH = Path('/run/matrix-path-events.lock')
THREAD_LOCK = threading.Lock()


@contextmanager
def locked(lock_path=LOCK_PATH, shared=False):
    with THREAD_LOCK, lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def append(value, path=LOG, lock_path=LOCK_PATH):
    with locked(lock_path), path.open('a') as stream:
        stream.write(json.dumps(value) + '\n')


def read(path=LOG, lock_path=LOCK_PATH):
    with locked(lock_path, shared=True):
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
