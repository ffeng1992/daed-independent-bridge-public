"""Bounded reads of disposable display history, never transaction authority.

Do not use this module to read credentials, active configuration, install pins,
recovery journals or locks. An unavailable history is UNKNOWN, not success.
"""
import hashlib
import json
import os
from pathlib import Path
import stat


class HistoryUnavailable(ValueError):
    """A value-free diagnostic: no history contents enter a response."""


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise HistoryUnavailable('HISTORY_DUPLICATE_KEY')
        result[key] = value
    return result


def read_json(path, *, limit=1024 * 1024, owner=None, mode=None):
    """Read one regular non-linked file; detect concurrent replacement/writes."""
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                before.st_size > limit or before.st_size < 0 or
                (owner is not None and before.st_uid != owner) or
                before.st_mode & 0o022 or
                (mode is not None and stat.S_IMODE(before.st_mode) != mode)):
            raise HistoryUnavailable('HISTORY_FILE_AUTHORITY')
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b''.join(chunks)
        after = os.fstat(fd)
        linked = path.lstat()
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns,
                               s.st_ctime_ns, s.st_nlink)
        if (signature(before) != signature(after) or
                signature(after) != signature(linked) or
                len(body) != before.st_size or len(body) > limit):
            raise HistoryUnavailable('HISTORY_READ_RACE')
        value = json.loads(body, object_pairs_hook=_pairs,
                           parse_constant=lambda _: _reject_number())
        if type(value) is not dict:
            raise HistoryUnavailable('HISTORY_SCHEMA')
        return value
    finally:
        os.close(fd)


def _reject_number():
    raise HistoryUnavailable('HISTORY_NONFINITE_NUMBER')


def optional_json(path, **kwargs):
    """Return (object, warning). No exception text or source values escape."""
    try:
        return read_json(path, **kwargs), None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError, TypeError, RecursionError):
        return None, 'HISTORY_UNAVAILABLE'


def preview_differences(root, previous, source, extensions):
    """An old comparison snapshot is optional; current inputs remain mandatory."""
    from bridge_m2.security import directory, read_at, Denied
    from .preview_diff import summary
    root = Path(root)
    before_source, before_extensions = {}, {}
    baseline, label = None, 'empty'
    try:
        saved, warning = optional_json(root / 'last-applied.json',
                                       owner=os.geteuid(), mode=0o600)
        if warning:
            raise HistoryUnavailable(warning)
        if saved is not None:
            ident = saved.get('previewId')
            if not _hex(ident):
                raise HistoryUnavailable('HISTORY_SCHEMA')
            baseline, label = root / 'previews' / ident, 'last-applied'
        elif previous:
            ident = previous['id']
            if not _hex(ident):
                raise HistoryUnavailable('HISTORY_SCHEMA')
            baseline, label = root / 'previews' / ident, 'previous-preview'
        if baseline is not None:
            fd = directory(baseline, os.geteuid(), os.getegid())
            try:
                raw_manifest = read_at(fd, 'manifest.json', os.geteuid(), os.getegid())
                if hashlib.sha256(raw_manifest).hexdigest() != ident:
                    raise HistoryUnavailable('HISTORY_IDENTITY')
                manifest = json.loads(raw_manifest)
                values = {}
                for name in ('source-snapshot.json', 'normalized-ir.json'):
                    raw = read_at(fd, name, os.geteuid(), os.getegid())
                    pin = manifest['files'][name]
                    if (len(raw) != pin['size'] or
                            hashlib.sha256(raw).hexdigest() != pin['sha256']):
                        raise HistoryUnavailable('HISTORY_IDENTITY')
                    values[name] = json.loads(raw)
                before_source = values['source-snapshot.json']
                before_extensions = values['normalized-ir.json']['extensions']
                if type(before_source) is not dict or type(before_extensions) is not dict:
                    raise HistoryUnavailable('HISTORY_SCHEMA')
            finally:
                os.close(fd)
        return {'daed': summary(before_source, source),
                'daeExtensions': summary(before_extensions, extensions),
                'baseline': label, 'available': True}
    except (OSError, ValueError, TypeError, KeyError, RecursionError, Denied):
        return {'daed': None, 'daeExtensions': None, 'baseline': 'history-unavailable',
                'available': False, 'reasonCode': 'HISTORY_UNAVAILABLE'}


def _hex(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def already_current(status, pending):
    """Use current helper evidence, not last-applied.json, for idempotency."""
    if (type(status) is not dict or status.get('error') or
            status.get('state') != 'running' or status.get('identityVerified') is not True or
            not _hex(status.get('activeBundle')) or
            status.get('sourceFingerprint') != pending['pins']['sourceSha256']):
        return False
    candidate = Path(pending['directory']) / 'candidate.dae'
    return hashlib.sha256(candidate.read_bytes()).hexdigest() == status.get('configSha256')
