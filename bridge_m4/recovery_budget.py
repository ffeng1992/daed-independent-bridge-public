"""A boot-bound monotonic retry budget; wall-clock history is display-only.

Legacy timestamps are converted once. Unknown/corrupt budgets conservatively
hold recovery for one window, while read-only health probes continue.
"""
import math
import time
from pathlib import Path

WINDOW = 900
MAX_ATTEMPTS = 2


def clock():
    return (Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            time.monotonic())


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def budget(record, wall_now, *, observed=None, uncertain=False):
    boot, mono = clock() if observed is None else observed
    if not isinstance(boot, str) or not boot or not _number(mono):
        raise RuntimeError('RECOVERY_CLOCK_UNAVAILABLE')
    old = record.get('retryBudget')
    valid = (type(old) is dict and set(old) == {'version', 'bootId', 'attempts', 'holdUntil'} and
             type(old.get('version')) is int and old['version'] == 1 and
             old.get('bootId') == boot and type(old.get('attempts')) is list and
             len(old['attempts']) <= MAX_ATTEMPTS and
             all(_number(x) and x <= mono for x in old['attempts']) and
             _number(old.get('holdUntil')) and old['holdUntil'] <= mono + WINDOW)
    if valid:
        value = {'version': 1, 'bootId': boot,
                 'attempts': [x for x in old['attempts'] if mono - x < WINDOW],
                 'holdUntil': old['holdUntil']}
    elif old is not None or uncertain:
        # New boot / damaged authority: one conservative finite hold, never
        # reinterpret old monotonic offsets in a different boot.
        value = {'version': 1, 'bootId': boot, 'attempts': [], 'holdUntil': mono + WINDOW}
    else:
        legacy = record.get('attempts', [])
        malformed = (type(legacy) is not list or len(legacy) > 100 or
                     any(not _number(x) for x in legacy) or not _number(wall_now))
        if malformed:
            value = {'version': 1, 'bootId': boot, 'attempts': [], 'holdUntil': mono + WINDOW}
        else:
            recent = [x for x in legacy if wall_now - x < WINDOW]
            # Future wall timestamps must not hold until a far-future date.
            # Two recent attempts consume the whole window conservatively.
            hold = bool(any(x > wall_now for x in recent) or len(recent) >= MAX_ATTEMPTS)
            value = {'version': 1, 'bootId': boot,
                     'attempts': [] if hold else [max(0, mono - (wall_now - x)) for x in recent],
                     'holdUntil': mono + WINDOW if hold else 0}
    record['retryBudget'] = value
    return value, mono


def permitted(record, wall_now, **kwargs):
    value, mono = budget(record, wall_now, **kwargs)
    return mono >= value['holdUntil'] and len(value['attempts']) < MAX_ATTEMPTS


def consume(record, wall_now, **kwargs):
    value, mono = budget(record, wall_now, **kwargs)
    if mono < value['holdUntil'] or len(value['attempts']) >= MAX_ATTEMPTS:
        return False
    value['attempts'].append(mono)
    # Keep a bounded human-facing history, not an authority for future retries.
    old = record.get('attempts', [])
    record['attempts'] = ([x for x in old if _number(x)][-MAX_ATTEMPTS + 1:]
                          if type(old) is list else []) + [wall_now]
    return True
