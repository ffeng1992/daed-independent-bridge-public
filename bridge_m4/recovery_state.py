"""Advisory health history recovery without resetting the restart safety budget."""
import hashlib
import json
import os
from pathlib import Path
import stat
from .advisory import optional_json
from .recovery_budget import budget

LIMIT = 1024 * 1024


def preserve_rejected(path):
    """Keep at most one bounded, private forensic copy; never follow links."""
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or
                    st.st_nlink != 1 or st.st_mode & 0o022 or st.st_size > LIMIT):
                return 'HISTORY_COPY_UNAVAILABLE'
            raw = os.read(fd, LIMIT + 1)
            if len(raw) != st.st_size:
                return 'HISTORY_COPY_UNAVAILABLE'
        finally:
            os.close(fd)
        target = path.with_name(path.name + '.rejected')
        try:
            out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            # Preserve prior evidence; do not accumulate unbounded backups.
            return 'HISTORY_COPY_ALREADY_RETAINED'
        with os.fdopen(out, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return 'HISTORY_COPY_SHA256:' + hashlib.sha256(raw).hexdigest()
    except OSError:
        return 'HISTORY_COPY_UNAVAILABLE'


def load(path, services, now, *, observed=None):
    value, warning = optional_json(path, owner=os.geteuid(), limit=LIMIT)
    damaged = warning is not None or (value is not None and
        (type(value.get('schemaVersion')) is not int or value['schemaVersion'] != 1 or
         type(value.get('services')) is not dict or type(value.get('history', [])) is not list))
    if value is None or damaged:
        value = {'schemaVersion': 1, 'services': {}, 'history': []}
    value.setdefault('history', [])
    value['history'] = [x for x in value['history'][-100:] if type(x) is dict and
                        type(x.get('event')) is str and type(x.get('at')) in (int, float)]
    if damaged:
        evidence = preserve_rejected(path)
        value['historyWarning'] = 'HISTORY_UNAVAILABLE'
        value['history'].append({'event': 'HISTORY_REBUILT', 'at': now,
            'evidence': evidence, 'needsAttention': False,
            'message': '旧巡检记录不可读；当前健康重新检查，自动恢复先保守限流。'})
    for name in services:
        existed = name in value['services']
        record = value['services'].get(name)
        invalid = type(record) is not dict
        if invalid:
            record = {}
            value['services'][name] = record
        count = record.get('consecutiveFailures', 0)
        if type(count) is not int or count < 0:
            record['consecutiveFailures'] = 0
            invalid = True
        # A missing service in otherwise valid history is new, not corrupted.
        uncertain = damaged or (invalid and existed)
        budget(record, now, observed=observed, uncertain=uncertain)
    return value
