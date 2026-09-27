"""DNS synchronization decision from fresh, verified independent DAE evidence.

This module has no database access, DAE lifecycle calls, or listening sockets.
An observation is never cached. A failed read immediately targets DAE DOWN.
The backend writer is supplied by the deployment-specific dnsdist integration.
"""
import re

HEX = re.compile(r'[0-9a-f]{64}\Z')


def decide(status, expected_config_sha256, actual_backends):
    """The expected hash must come from the verified active version authority.

    DIRECT retains the existing inverse fallback policy. Invalid identity is
    distinguishable from a legitimate stop even after backend convergence.
    """
    valid = type(status) is dict
    raw = status.get('systemd') if valid else None
    schema = (valid and type(raw) is dict
              and type(status.get('MainPID')) is int
              and type(status.get('InvocationID')) is str
              and type(status.get('identityVerified')) is bool)
    healthy = bool(schema and status.get('state') == 'running'
                   and raw.get('ActiveState') == 'active'
                   and raw.get('SubState') == 'running'
                   and status['MainPID'] > 0
                   and raw.get('MainPID') == str(status['MainPID'])
                   and re.fullmatch(r'[0-9a-f]{32}', status['InvocationID'])
                   and raw.get('InvocationID') == status['InvocationID']
                   and status['identityVerified'] is True
                   and type(status.get('activeBundle')) is str
                   and HEX.fullmatch(status['activeBundle'])
                   and type(expected_config_sha256) is str
                   and HEX.fullmatch(expected_config_sha256)
                   and status.get('configSha256') == expected_config_sha256
                   and not any(k in status for k in ('error', 'recoveryBundle', 'phase')))
    stopped = bool(schema and status.get('state') == 'stopped'
                   and raw.get('ActiveState') == 'inactive'
                   and raw.get('SubState') == 'dead'
                   and status['MainPID'] == 0 and raw.get('MainPID') == '0'
                   and not any(k in status for k in ('error', 'recoveryBundle', 'phase')))
    target = {'DAE': 'UP' if healthy else 'DOWN',
              'DIRECT': 'DOWN' if healthy else 'UP'}
    return {'target': target, 'consistent': bool((healthy or stopped) and actual_backends == target),
            'sourceValid': healthy or stopped,
            'reason': 'VERIFIED_RUNNING' if healthy else 'VERIFIED_STOPPED' if stopped else 'UNVERIFIED_DAE_STATE'}


def reconcile(reader, backend):
    """Enable DIRECT before disabling DAE on failure; never cache an UP result.

    reader returns a fresh authority-verified status and active candidate hash.
    backend exposes only states() and set_state('DAE'|'DIRECT', 'UP'|'DOWN').
    Evidence read failures are deliberately DOWN, never a default success.
    """
    try:
        status, expected = reader()
    except Exception:
        status, expected = None, None
    result = decide(status, expected, backend.states())
    target = result['target']
    first = 'DAE' if target['DAE'] == 'UP' else 'DIRECT'
    second = 'DIRECT' if first == 'DAE' else 'DAE'
    # On lost authority, DAE must be disabled even if the fallback fails.
    if target['DAE'] == 'DOWN':
        try:
            backend.set_state('DIRECT', 'UP')
        finally:
            backend.set_state('DAE', 'DOWN')
    for name in (first, second):
        if backend.states().get(name) != target[name]:
            backend.set_state(name, target[name])
        if backend.states().get(name) != target[name]:
            raise RuntimeError('DNS_BACKEND_TRANSITION_FAILED')
    # Re-read after side effects: a crash during the switch must not report UP.
    try:
        current, expected = reader()
    except Exception:
        current, expected = None, None
    final = decide(current, expected, backend.states())
    if final['target']['DAE'] == 'DOWN' and backend.states().get('DAE') == 'UP':
        try:
            backend.set_state('DIRECT', 'UP')
        finally:
            backend.set_state('DAE', 'DOWN')
        if backend.states().get('DIRECT') != 'UP':
            raise RuntimeError('DNS_BACKEND_TRANSITION_FAILED')
        final = decide(current, expected, backend.states())
    return final
