"""Bounded recovery for the independent bridge management plane only."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
import urllib.request

CFG = Path('/etc/daed-independent-bridge')
STATE = Path('/var/lib/daed-independent-bridge/management-recovery.json')
PAUSE = CFG / 'management-recovery.pause'


def control_path(environ=None):
    values = os.environ if environ is None else environ
    return Path(values.get('BRIDGE_MANAGEMENT_CONTROL_DIR',
                           '/var/lib/bridge-m4-client/management-recovery'))


WEB_CONTROL = control_path()
WEB_PAUSE = WEB_CONTROL / 'pause.json'
WEB_RESUME = WEB_CONTROL / 'resume.json'
APPLY_LOCK = Path('/var/lib/daed-independent-bridge/apply.lock')
RELEASE_LOCK = Path('/run/bridge-release.lock')
WINDOW = 15 * 60
MAX_ATTEMPTS = 2
HISTORY_LIMIT = 100
SERVICES = (('daed-api.service', 'api'), ('bridge-graphql.service', 'adapter'),
            ('bridge-attestor.service', 'attestor'), ('daed-web.service', 'web'),
            ('independent-bridge.service', 'bridge'))


def need(value, code):
    if not value:
        raise RuntimeError(code)


def systemctl(*args):
    return subprocess.run(['/usr/bin/systemctl', *args], capture_output=True,
                          check=True, timeout=20, text=True)


def show(name):
    raw = systemctl('show', name, '--property=LoadState,ActiveState,SubState,MainPID').stdout
    return dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)


def request(url, *, body=None, context=None):
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    req = urllib.request.Request(url, data=body, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                          urllib.request.HTTPSHandler(context=context))
    with opener.open(req, timeout=5) as response:
        data = response.read(1024 * 1024)
        need(response.status == 200, 'HTTP_STATUS')
        return data


def graphql(port):
    value = json.loads(request('http://127.0.0.1:%d/graphql' % port,
                               body=b'{"query":"{numberUsers}"}'))
    need(type(value.get('data', {}).get('numberUsers')) is int, 'GRAPHQL_RESPONSE')


def endpoint(kind):
    if kind == 'api':
        graphql(2024)
    elif kind == 'adapter':
        graphql(2025)
    elif kind == 'web':
        config = json.loads((CFG / 'web.json').read_text())
        request('http://%s:2023/' % config['address'])
    elif kind == 'bridge':
        config = json.loads((CFG / 'web.json').read_text())
        context = ssl.create_default_context(cafile=str(CFG / 'tls.crt'))
        value = json.loads(request(config['origin'] + '/api/challenge', context=context))
        need(type(value.get('csrf')) is str and bool(value['csrf']), 'BRIDGE_RESPONSE')
    elif kind == 'attestor':
        receipt = Path('/var/lib/bridge-m4-attestation/receipt.json')
        if receipt.exists():
            value = json.loads(receipt.read_text())
            need(set(('schemaVersion', 'sourceSha256', 'expiresAt')) <= set(value),
                 'ATTESTOR_STATE')


def healthy(name, kind):
    try:
        unit = show(name)
        need(unit.get('LoadState') == 'loaded' and unit.get('ActiveState') == 'active'
             and int(unit.get('MainPID', '0')) > 0, 'SERVICE_STATE')
        endpoint(kind)
        return True, ''
    except Exception as exc:
        return False, type(exc).__name__ + ':' + str(exc)


def wait_healthy(name, kind, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        ok, error = healthy(name, kind)
        if ok or time.monotonic() >= deadline:
            return ok, error
        time.sleep(.25)


def load_state(now=None):
    from bridge_m4.recovery_state import load
    now = int(time.time()) if now is None else now
    return load(STATE, [name for name, _ in SERVICES], now)


def save_state(value):
    STATE.parent.mkdir(mode=0o711, parents=True, exist_ok=True)
    temp = STATE.with_suffix('.next')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'))
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), 0o640)
    os.replace(temp, STATE)
    directory = os.open(STATE.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def append_history(state, event, now, **fields):
    history = state.setdefault('history', [])
    history.append({'at': now, 'event': event, **fields})
    del history[:-HISTORY_LIMIT]


def maintenance_guard(*, allow_web_paused=False):
    need(not PAUSE.exists(), 'MAINTENANCE_PAUSED')
    need(allow_web_paused or not WEB_PAUSE.exists(), 'MAINTENANCE_PAUSED')
    from bridge_m4.maintenance_state import primary_guard, install_guard
    primary_guard()
    install_guard()
    tx = Path('/var/lib/daed-independent-bridge/transaction.json')
    if tx.exists():
        value = json.loads(tx.read_text())
        need(value.get('phase') in {'HEALTHY', 'ROLLED_BACK', 'STOPPED'},
             'TRANSACTION_IN_PROGRESS')
        need(not value.get('rollbackNeeded'), 'ROLLBACK_REQUIRED')
    from bridge_m4.authority import manifest
    manifest()


def process_resume_request(now):
    if not WEB_RESUME.exists():
        return False
    need(WEB_RESUME.is_file() and not WEB_RESUME.is_symlink(), 'RESUME_REQUEST_IDENTITY')
    need(WEB_PAUSE.is_file() and not WEB_PAUSE.is_symlink(), 'PAUSE_MARKER_IDENTITY')
    maintenance_guard(allow_web_paused=True)
    WEB_RESUME.unlink()
    WEB_PAUSE.unlink()
    directory = os.open(WEB_CONTROL, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    log('管理员的自动恢复请求已通过维护锁与事务门禁。', resumed=True, at=now)
    return True


def locks():
    handles = []
    need(APPLY_LOCK.is_file() and not APPLY_LOCK.is_symlink(), 'APPLY_LOCK_IDENTITY')
    try:
        for path, flags in ((RELEASE_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW),
                            (APPLY_LOCK, os.O_RDWR | os.O_NOFOLLOW)):
            fd = os.open(path, flags, 0o600)
            handles.append(fd)
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return handles
    except Exception:
        close_locks(handles)
        raise


def close_locks(handles):
    for fd in reversed(handles):
        os.close(fd)


def guarded(*, allow_web_paused=False):
    """Probe the shared maintenance gates without delaying an Apply operation."""
    handles = locks()
    try:
        maintenance_guard(allow_web_paused=allow_web_paused)
    finally:
        if handles:
            close_locks(handles)


def log(message, **fields):
    print(json.dumps({'message': message, **fields}, ensure_ascii=False,
                     sort_keys=True), flush=True)


def recover(name, kind, record, state, now):
    from bridge_m4.recovery_budget import permitted, consume
    if not permitted(record, now):
        log('管理服务连续恢复失败，已停止重复尝试，需要检查。', service=name,
            impact=kind, rateLimited=True)
        if record.get('rateLimitActive') is not True:
            record['rateLimitActive'] = True
            record['lastRateLimitedAt'] = now
            append_history(state, 'RECOVERY_RATE_LIMITED', now, service=name,
                           impact=kind, needsAttention=True)
        return False
    began = time.monotonic()
    action = 'restart' if show(name).get('ActiveState') == 'active' else 'start'
    need(consume(record, now), 'RECOVERY_RATE_LIMITED')
    record['rateLimitActive'] = False
    # Persist the safety budget before the restart; a crashed checker cannot
    # forget an already-issued recovery action.
    save_state(state)
    try:
        systemctl(action, name)
        ok, error = wait_healthy(name, kind)
    except Exception as exc:
        ok, error = False, type(exc).__name__ + ':' + str(exc)
    record['lastRecoveryAt'] = now; record['lastRecoverySucceeded'] = ok
    record['lastRecoveryElapsedMs'] = int((time.monotonic() - began) * 1000)
    append_history(state, 'RECOVERY_SUCCEEDED' if ok else 'RECOVERY_FAILED', now,
                   service=name, impact=kind, action=action, recovered=ok,
                   elapsedMs=record['lastRecoveryElapsedMs'], error=error,
                   needsAttention=not ok)
    log('管理服务已自动恢复。' if ok else '管理服务恢复失败，需要检查。',
        service=name, impact=kind, action=action, recovered=ok,
        elapsedMs=record['lastRecoveryElapsedMs'], error=error)
    return ok


def check_once(now=None):
    now = int(time.time()) if now is None else now
    handles = []
    try:
        # Observations do not reserve the configuration writer's locks. The
        # expensive manifest/unit checks may overlap an Apply; their result is
        # never authority to mutate services. Recheck under locks at recovery.
        if WEB_PAUSE.exists() and WEB_RESUME.exists():
            handles = locks()
            try:
                process_resume_request(now)
            finally:
                close_locks(handles); handles = []
        maintenance_guard()
    except (BlockingIOError, RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        log('管理层处于维护或身份异常状态，自动恢复未执行。',
            error=type(exc).__name__ + ':' + str(exc))
        close_locks(handles); return 0
    # HTTP observations are unlocked. Only a recovery action reserves the
    # maintenance gates, from its final validation through its actual action.
    state = load_state(now)
    try:
        state['lastCheckStartedAt'] = now
        for name, kind in SERVICES:
            record = state['services'].setdefault(name, {})
            ok, error = healthy(name, kind)
            try: unit = show(name)
            except Exception: unit = {}
            record.update({'checkedAt': now, 'healthy': ok,
                           'activeState': unit.get('ActiveState', 'unknown'),
                           'subState': unit.get('SubState', 'unknown'),
                           'mainPid': int(unit.get('MainPID', '0') or 0)})
            if ok:
                if int(record.get('consecutiveFailures', 0)):
                    append_history(state, 'SERVICE_HEALTH_RESTORED', now,
                                   service=name, impact=kind, recovered=True,
                                   needsAttention=False)
                record['consecutiveFailures'] = 0; record['lastHealthyAt'] = now
                record['lastError'] = ''
                continue
            failures = int(record.get('consecutiveFailures', 0)) + 1
            record['consecutiveFailures'] = failures
            record['lastFailureAt'] = now; record['lastError'] = error
            log('管理服务健康检查失败。', service=name, impact=kind,
                consecutiveFailures=failures, error=error)
            if failures == 1:
                append_history(state, 'SERVICE_HEALTH_FAILED', now,
                               service=name, impact=kind, error=error,
                               needsAttention=False)
            if failures >= 2:
                try:
                    handles = locks()
                    maintenance_guard()
                except (BlockingIOError, RuntimeError, OSError, ValueError,
                        json.JSONDecodeError) as exc:
                    log('管理层进入维护状态，本轮恢复已跳过。', service=name,
                        error=type(exc).__name__ + ':' + str(exc))
                    close_locks(handles); handles = []
                    continue
            try:
                recovered = failures >= 2 and recover(name, kind, record, state, now)
            finally:
                close_locks(handles); handles = []
            if recovered:
                record['consecutiveFailures'] = 0
                record['healthy'] = True
                record['lastError'] = ''
                try: unit = show(name)
                except Exception: unit = {}
                record.update({'activeState': unit.get('ActiveState', 'unknown'),
                               'subState': unit.get('SubState', 'unknown'),
                               'mainPid': int(unit.get('MainPID', '0') or 0)})
        state['lastCheckCompletedAt'] = int(time.time()) if now is None else now
        state['lastCheckResult'] = ('HEALTHY' if all(
            state['services'][name].get('healthy') is True for name, _ in SERVICES)
            else 'DEGRADED')
        save_state(state)
    finally:
        if handles:
            close_locks(handles)
    return 0


def capture(path):
    value = {'schemaVersion': 1, 'services': {
        name: show(name).get('ActiveState') == 'active' for name, _ in SERVICES}}
    target = Path(path); target.write_text(json.dumps(value, sort_keys=True) + '\n')
    os.chmod(target, 0o600)


def restore(path):
    value = json.loads(Path(path).read_text())
    need(value.get('schemaVersion') == 1 and set(value.get('services', {})) ==
         {name for name, _ in SERVICES}, 'MANAGEMENT_STATE_SCHEMA')
    maintenance_guard()
    for name, kind in SERVICES:
        if value['services'][name] and not healthy(name, kind)[0]:
            systemctl('start', name)
            need(wait_healthy(name, kind)[0], 'MANAGEMENT_RESTORE_FAILED:' + name)


def main(argv=None):
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--pause', action='store_true'); group.add_argument('--resume', action='store_true')
    group.add_argument('--capture'); group.add_argument('--restore')
    args = parser.parse_args(argv)
    if args.pause:
        PAUSE.write_text('Paused by administrator.\n'); os.chmod(PAUSE, 0o600); return 0
    if args.resume:
        PAUSE.unlink(missing_ok=True); return 0
    if args.capture: capture(args.capture); return 0
    if args.restore: restore(args.restore); return 0
    return check_once()


def entrypoint(argv=None):
    try:
        return main(argv)
    except Exception as exc:
        log('管理层自动恢复检查失败，需要人工检查。',
            error=type(exc).__name__ + ':' + str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(entrypoint())
