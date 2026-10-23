"""Read-only interpretation of completed PRIMARY rollback attempts.

Unknown/partial records fail closed. A completed record is historical only when
all attempt bindings agree and neither protection phase can still execute.
No history is deleted, rewritten, or compared with a long-dead process PID.
"""
from pathlib import Path
import os
import stat
import subprocess
from .advisory import read_json

STATE = Path('/var/lib/primary-rollback')
AUTHORITY = Path('/etc/primary-rollback/attempt.json')
TERMINAL = {'ROLLED_BACK', 'ALREADY_ROLLED_BACK'}


def need(ok, code='ROLLBACK_REQUIRED'):
    if not ok:
        raise RuntimeError(code)


def _read(path):
    # Fixed parent authority plus no-follow traversal, not an optional history read.
    path = Path(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parent.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        st = os.fstat(fd)
        need(st.st_uid == 0 and not st.st_mode & 0o022, 'ROLLBACK_STATE_AUTHORITY')
    finally:
        os.close(fd)
    return read_json(path, owner=0, mode=0o600, limit=4 * 1024 * 1024)


def _bound(item, authority, phase):
    expected = {'attemptId': authority['attemptId'], 'phase': phase,
                'primaryVersion': 'primary-7ed6de2-v7',
                'candidateSha': authority['candidateSha'],
                'manifestSha256': authority['rollbackManifestSha256'],
                'databaseSha256': authority['databaseSha256'],
                'bundleSha256': authority['activeBundle']}
    return type(item) is dict and all(item.get(k) == v for k, v in expected.items())


def completed_snapshot(authority, tx, records, units):
    """Pure interpretation, suitable for synthetic tests and read-only callers."""
    try:
        need(type(authority) is dict and type(tx) is dict)
        for key in ('attemptId', 'candidateSha', 'rollbackManifestSha256',
                    'databaseSha256', 'activeBundle'):
            need(type(authority.get(key)) is str and bool(authority[key]) and
                 tx.get(key) == authority[key])
        need(tx.get('phase') in {'phase1', 'phase2'} and tx.get('rollbackRequired') is False)
        need('rollback-required.json' not in records and 'checkpoint.json' not in records)
        protection_quiescent(units)
        phase = tx['phase']
        armed = records.get(phase + '-armed.json')
        need(_bound(armed, authority, phase) and type(tx.get('deadline')) is int and
             armed.get('deadline') == tx['deadline'])
        if tx.get('checkpoint') == 'ROLLED_BACK' and tx.get('rollbackResult') in TERMINAL:
            result = records.get('rollback-result.json')
            need(_bound(result, authority, phase) and result.get('result') == tx['rollbackResult'])
            return True
        need(phase == 'phase2' and tx.get('checkpoint') == 'PHASE2_ACCEPTED' and
             tx.get('finalAccepted') is True and tx.get('phase1Accepted') is True and
             tx.get('rollbackResult') is None)
        checks = {'identity', 'configuration', 'dns', 'tcp', 'udp', 'kernel', 'web', 'singleDataPlane'}
        for p, filename in (('phase1', 'phase1-accepted.json'), ('phase2', 'final-accepted.json')):
            arming, accepted = records.get(p + '-armed.json'), records.get(filename)
            need(_bound(arming, authority, p) and _bound(accepted, authority, p))
            need(type(arming.get('deadline')) is int and arming['deadline'] == accepted.get('deadline'))
            evidence = accepted.get('evidence')
            need(type(evidence) is dict and evidence.get('passed') is True and
                 evidence.get('attemptId') == authority['attemptId'] and
                 evidence.get('candidateSha') == authority['candidateSha'] and
                 evidence.get('activeBundle') == authority['activeBundle'] and
                 type(evidence.get('checks')) is dict and set(evidence['checks']) == checks and
                 all(v is True for v in evidence['checks'].values()))
        return True
    except (KeyError, TypeError, ValueError):
        raise RuntimeError('ROLLBACK_STATE_UNRECOGNIZED') from None


PROTECTION_UNITS = tuple(f'primary-rollback-{phase}.{kind}'
                         for phase in ('phase1', 'phase2') for kind in ('service', 'timer'))
STATE_NAMES = ('rollback-required.json', 'checkpoint.json', 'phase1-armed.json',
               'phase2-armed.json', 'phase1-accepted.json', 'final-accepted.json',
               'rollback-result.json', 'transaction.json')


def protection_quiescent(units):
    """No file absence can establish that a systemd trigger is safe."""
    need(type(units) is dict and set(units) == set(PROTECTION_UNITS),
         'ROLLBACK_PROTECTION_UNKNOWN')
    for name in PROTECTION_UNITS:
        u = units[name]
        need(type(u) is dict and u.get('LoadState') in {'loaded', 'masked', 'not-found'}
             and u.get('ActiveState') == 'inactive', 'ROLLBACK_PROTECTION_ACTIVE_OR_UNKNOWN')
        absent = u['LoadState'] == 'not-found'
        # An absent unit may omit fields, but contradictory fields still reject.
        if name.endswith('.service'):
            for key in ('MainPID', 'ControlPID'):
                need(u.get(key, '0' if absent else None) == '0',
                     'ROLLBACK_PROTECTION_PROCESS')
        else:
            need(u.get('UnitFileState', '' if absent else None) in
                 ({'', 'not-found', 'disabled', 'masked'} if absent else {'disabled', 'masked'}),
                 'ROLLBACK_PROTECTION_ARMED')
            for key in ('NextElapseUSecRealtime', 'NextElapseUSecMonotonic'):
                need(u.get(key, '0' if absent else None) in {'', '0', 'infinity'},
                     'ROLLBACK_PROTECTION_SCHEDULED')
    return True


def _unit(name):
    need(name in PROTECTION_UNITS, 'ROLLBACK_PROTECTION_UNKNOWN')
    result = subprocess.run(['/usr/bin/systemctl', 'show', name, '--all',
            '--property=LoadState,ActiveState,MainPID,ControlPID,UnitFileState,NextElapseUSecRealtime,NextElapseUSecMonotonic'],
            check=False, capture_output=True, text=True, timeout=5)
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    # A never-installed unit can produce a nonzero show result. Only an
    # explicit absent + inactive property response can distinguish that from
    # a bus/permission/transport failure. The full guard checks other fields.
    need(result.returncode == 0 or
         (result.returncode in (1, 4) and fields.get('LoadState') == 'not-found' and
          fields.get('ActiveState') == 'inactive'), 'ROLLBACK_PROTECTION_QUERY_FAILED')
    return fields


def _present(path):
    # Broken symlinks are present, not evidence of an absent transaction.
    return path.exists() or path.is_symlink()


def primary_guard(state=STATE, authority=AUTHORITY, *, read=_read, show=_unit):
    state, authority = Path(state), Path(authority)
    units = {name: show(name) for name in PROTECTION_UNITS}
    protection_quiescent(units)
    exists = {name for name in STATE_NAMES if _present(state / name)}
    if not exists:
        need(not _present(authority), 'ROLLBACK_STATE_INCOMPLETE')
    else:
        # Unknown markers and explicit pending rollback never become a warning.
        need(not exists & {'rollback-required.json', 'checkpoint.json'})
        need('transaction.json' in exists)
        records = {name: read(state / name) for name in exists}
        auth = read(authority)
        completed_snapshot(auth, records['transaction.json'],
                           {k: v for k, v in records.items() if k != 'transaction.json'}, units)
        # Do not mix one attempt's state with another attempt's unit observation.
        need(read(authority) == auth and
             all(read(state / name) == value for name, value in records.items()),
             'ROLLBACK_STATE_CHANGED')
    need({name for name in STATE_NAMES if _present(state / name)} == exists,
         'ROLLBACK_STATE_CHANGED')
    after = {name: show(name) for name in PROTECTION_UNITS}
    protection_quiescent(after)
    need(after == units and (bool(exists) or not _present(authority)) and
         {name for name in STATE_NAMES if _present(state / name)} == exists,
         'ROLLBACK_STATE_CHANGED')



def install_guard(root=Path('/var/lib/bridge-m4-install'), *, read=_read):
    """Incomplete program publication blocks automatic service recovery."""
    root=Path(root)
    for name,terminal in (('transaction.json',{'COMMITTED','RESTORED'}),
                          ('native-lifecycle.json',{'ACCEPTED','RESTORED'})):
        path=root/name
        if not _present(path):continue
        value=read(path)
        need(type(value) is dict and value.get('phase') in terminal,
             'INSTALL_TRANSACTION_IN_PROGRESS')
        need(read(path)==value,'INSTALL_TRANSACTION_CHANGED')
