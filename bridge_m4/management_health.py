"""Authenticated Bridge view and maintenance control for recovery V1."""
import json
import os
from pathlib import Path
import time

from bridge_m2.security import check, atomic_json

STATE = Path('/var/lib/daed-independent-bridge/management-recovery.json')
WEB_CONTROL = Path('/var/lib/bridge-m4-client/management-recovery')
WEB_PAUSE = WEB_CONTROL / 'pause.json'
WEB_RESUME = WEB_CONTROL / 'resume.json'
LEGACY_PAUSE = Path('/etc/daed-independent-bridge/management-recovery.pause')
FRESH_SECONDS = 180
COMPONENTS = {
    'independent-bridge.service': ('Bridge 管理页面', '独立 DAE 管理功能不可用，不影响现有数据面'),
    'daed-api.service': ('官方 daed API', '官方配置管理不可用，不影响现有数据面'),
    'bridge-graphql.service': ('GraphQL 兼容入口', '官方 daed 页面部分管理功能不可用，不影响现有数据面'),
    'bridge-attestor.service': ('配置签发组件', '新的预览和校验收据不可生成，不影响现有数据面'),
    'daed-web.service': ('官方 daed 页面', '官方配置页面不可访问，不影响现有数据面'),
}


def _read_json(path, limit=1024 * 1024):
    check(path.is_file() and not path.is_symlink(), 'MANAGEMENT_HEALTH_STATE')
    raw = path.read_bytes()
    check(len(raw) <= limit, 'MANAGEMENT_HEALTH_STATE')
    value = json.loads(raw)
    check(type(value) is dict, 'MANAGEMENT_HEALTH_STATE')
    return value


def _state():
    if not STATE.exists():
        return {'schemaVersion': 1, 'services': {}, 'history': []}
    value = _read_json(STATE)
    check(value.get('schemaVersion') == 1 and type(value.get('services')) is dict
          and type(value.get('history', [])) is list, 'MANAGEMENT_HEALTH_STATE')
    return value


def _paused():
    return WEB_PAUSE.exists() or LEGACY_PAUSE.exists()


def _write_pause(now):
    WEB_CONTROL.mkdir(mode=0o770, parents=True, exist_ok=True)
    os.chmod(WEB_CONTROL, 0o770)
    WEB_RESUME.unlink(missing_ok=True)
    atomic_json(WEB_PAUSE, {'schemaVersion': 1, 'pausedAt': now,
                            'reason': '管理员通过 Bridge 页面暂停'})


def _request_resume(now):
    check(WEB_PAUSE.is_file() and not WEB_PAUSE.is_symlink(),
          'MANAGEMENT_RECOVERY_NOT_PAUSED')
    atomic_json(WEB_RESUME, {'schemaVersion': 1, 'requestedAt': now,
                             'reason': '管理员通过 Bridge 页面请求恢复'})


def set_paused(paused, *, now=None):
    check(type(paused) is bool, 'MANAGEMENT_RECOVERY_REQUEST')
    now = int(time.time()) if now is None else now
    if paused:
        _write_pause(now)
    else:
        _request_resume(now)
    return status(now=now)


def status(*, now=None):
    now = int(time.time()) if now is None else now
    state = _state()
    completed = state.get('lastCheckCompletedAt')
    fresh = type(completed) is int and 0 <= now - completed <= FRESH_SECONDS
    components = []
    attention = False
    for service, (title, impact) in COMPONENTS.items():
        record = state['services'].get(service, {})
        healthy = record.get('healthy') is True and fresh
        failures = int(record.get('consecutiveFailures', 0) or 0)
        needs_attention = failures >= 2 or record.get('lastRecoverySucceeded') is False
        attention = attention or needs_attention or not healthy
        components.append({
            'service': service,
            'title': title,
            'healthy': healthy,
            'activeState': record.get('activeState', 'unknown'),
            'subState': record.get('subState', 'unknown'),
            'mainPid': record.get('mainPid', 0),
            'checkedAt': record.get('checkedAt'),
            'consecutiveFailures': failures,
            'lastError': record.get('lastError') or None,
            'lastRecoveryAt': record.get('lastRecoveryAt'),
            'lastRecoverySucceeded': record.get('lastRecoverySucceeded'),
            'impact': impact,
            'internetAffected': False,
            'needsAttention': needs_attention,
        })
    history = []
    for event in state.get('history', [])[-100:]:
        if type(event) is not dict:
            continue
        service = event.get('service')
        title = COMPONENTS.get(service, (service or '管理系统', ''))[0]
        history.append({**event, 'title': title})
    paused = _paused()
    resume_pending = WEB_RESUME.exists()
    if paused:
        overall = 'PAUSED'
        summary = ('恢复请求已提交，等待底层巡检完成维护锁与事务门禁。'
                   if resume_pending else
                   '自动恢复已由管理员暂停；现有网络数据面不受此状态直接影响。')
    elif not fresh:
        overall = 'UNKNOWN'
        summary = '巡检结果已过期或尚未生成，需要检查定时巡检。'
    elif attention:
        overall = 'ATTENTION_REQUIRED'
        summary = '管理功能存在未恢复问题，需要人工检查；不会自动修改 DAE、DNS 或代理配置。'
    else:
        overall = 'HEALTHY'
        summary = '管理系统健康，自动恢复正在运行。'
    recovery = next((event for event in reversed(history)
                     if event.get('event', '').startswith('RECOVERY_')), None)
    return {
        'schemaVersion': 1,
        'overall': overall,
        'summary': summary,
        'paused': paused,
        'resumePending': resume_pending,
        'lastCheckAt': completed,
        'lastCheckFresh': fresh,
        'lastCheckResult': state.get('lastCheckResult', 'NOT_RUN'),
        'lastRecovery': recovery,
        'needsAttention': overall in {'UNKNOWN', 'ATTENTION_REQUIRED'},
        'notification': {
            'activeChannel': None,
            'description': '当前没有经过验证的主动推送渠道；故障记录保存在 Bridge 页面和 systemd journal。',
        },
        'components': components,
        'history': list(reversed(history)),
    }
