"""Bounded v0.3.1 -> Stage 2B management-only update.

The official services, DAE process, DNS listeners, and persistent state are
outside the write set. This is deliberately not a general upgrade engine.
"""
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from scripts import m4_install
from scripts.m4_install_transaction import begin, commit, exclusive, restore, write
from scripts.release_replace import (ctl, database_snapshot,
                                     show, source_identity, verify_management,
                                     wait_sync_idle)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path('/etc/daed-independent-bridge/install.json')
BOUNDED = json.loads((ROOT/'scripts/management-upgrade-v031.json').read_text())
EXTERNAL_DNS_UNITS = frozenset('/etc/systemd/system/' + name for name in (
    'bridge-lan-dns.service', 'bridge-policy-dns.service',
    'independent-dns-sync.service', 'independent-dns-sync.timer',
    'independent-policy-sync.service', 'independent-policy-sync.timer'))
MANAGEMENT = ('bridge-graphql.service', 'independent-bridge.service',
              'bridge-attestor.service', 'bridge-helper.socket', 'bridge-helper.service')
WEB_UNIT = 'daed-web.service'
TIMERS = ('independent-dns-sync.timer', 'independent-policy-sync.timer')
SYNC = ('independent-dns-sync.service', 'independent-policy-sync.service')
PRESERVED = ('dae.service', 'daed-api.service',
             'bridge-policy-dns.service', 'bridge-lan-dns.service')


def need(value, code):
    if not value:
        raise RuntimeError(code)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def plan(old, files):
    """Refuse any source, official, DNS, or unit change outside the fixed set."""
    previous = old['files']
    desired = {name: {'sha256': sha(body), 'mode': mode}
               for name, (body, mode) in sorted(files.items())}
    pins = BOUNDED['files']
    need(set(desired) == set(previous) | {p for p, old_sha in pins.items() if old_sha is None},
         'MANAGEMENT_FILE_SET')
    for name, old_sha in pins.items():
        need((previous[name]['sha256'] if name in previous else None) == old_sha,
             'MANAGEMENT_BASELINE_MISMATCH')
        need(name in desired and desired[name]['mode'] == 0o644,
             'MANAGEMENT_CANDIDATE_MISSING')
    changed = {name for name in desired if desired[name] != previous.get(name)}
    need(changed == set(pins), 'MANAGEMENT_SCOPE_CHANGED')
    return desired, changed


def management_payload(old):
    """Build the full release, then retain existing DNS ownership exactly."""
    from scripts.release_lifecycle import ready_payload
    full = ready_payload()
    previous = set(old['files'])
    new_contracts = {name for name, pin in BOUNDED['files'].items() if pin is None}
    external = EXTERNAL_DNS_UNITS - previous
    need(set(full) - previous - new_contracts == external, 'MANAGEMENT_FILE_SET')
    return {name: value for name, value in full.items() if name not in external}


def running_identity():
    dae = show('dae.service')
    need(dae.get('ActiveState') == 'active' and int(dae.get('MainPID', 0)) > 0,
         'DAE_NOT_RUNNING')
    web = verify_management()
    need(str(web.get('MainPID')) == dae['MainPID'] and web.get('InvocationID') == dae['InvocationID']
         and web.get('identityVerified') is True, 'DAE_IDENTITY_MISMATCH')
    return {'dae': dae, 'bundle': web.get('activeBundle'),
            'configSha256': web.get('configSha256')}


def unchanged(before):
    after = running_identity()
    for key in ('MainPID', 'InvocationID', 'NRestarts'):
        need(after['dae'].get(key) == before['dae'].get(key), 'DAE_PROCESS_CHANGED')
    need(after['bundle'] == before['bundle'] and
         after['configSha256'] == before['configSha256'], 'DAE_CONFIGURATION_CHANGED')
    return after


def verify_installed_dns(current):
    # A clean release installation ships the packaged dnsdist controller.
    # Existing-production integration keeps its separately installed DNS
    # controller and must use the corresponding read-only verification path.
    if '/etc/systemd/system/bridge-lan-dns.service' in current['files']:
        from scripts.release_health import check
        check()
    else:
        verify_external_dns()


def verify_external_dns():
    """Read-only existing-production DNS check without a release health.json."""
    from bridge_m4.dns_sync_runtime import Backends, read_status
    from bridge_m4.dns_sync import decide
    from scripts.release_health import dns
    status, expected = read_status()
    need(status.get('state') == 'running' and status.get('identityVerified') is True
         and status.get('configSha256') == expected, 'DAE_IDENTITY')
    backends = Backends().states()
    need(backends == {'DAE': 'UP', 'DIRECT': 'DOWN'} and
         decide(status, expected, backends)['consistent'], 'DNS_SYNC_STATUS')
    config = Path('/etc/dnsdist/dnsdist.conf').read_text()
    listeners = re.findall(r'(?m)^\s*(?:setLocal|addLocal)\("([0-9.]+):([0-9]+)"\)\s*$', config)
    need(len(listeners) == 1 and listeners[0][1] == '53', 'DNS_LISTENER_IDENTITY')
    ip = ipaddress.IPv4Address(listeners[0][0])
    need(not ip.is_unspecified and not ip.is_loopback, 'DNS_LISTENER_IDENTITY')
    address = str(ip)
    for host, port in ((address, 53), ('127.0.0.1', 5353)):
        for tcp in (False, True):
            dns(host, port, 'www.baidu.com', tcp)


def stop_management():
    ctl('stop', *TIMERS)
    wait_sync_idle()
    # The official dashboard unit Requires bridge-graphql.service. Stopping
    # the adapter also stops the dashboard, so include it in this management
    # restart rather than misclassifying it as a preserved dataplane service.
    ctl('stop', WEB_UNIT)
    ctl('stop', *MANAGEMENT)


def start_management():
    ctl('start', 'bridge-helper.socket', 'bridge-attestor.service',
        'independent-bridge.service', 'bridge-graphql.service')
    ctl('start', WEB_UNIT)
    verify_management()
    ctl('start', *TIMERS)


def execute(*, restore_only=False):
    need(os.geteuid() == 0 and Path('/run/systemd/system').is_dir(),
         'DEBIAN_SYSTEMD_ROOT_REQUIRED')
    need(MANIFEST.is_file() and not MANIFEST.is_symlink(), 'EXISTING_MANIFEST_REQUIRED')
    with open('/run/bridge-release.lock', 'a') as release_lock, exclusive():
        fcntl.flock(release_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = json.loads(MANIFEST.read_text())
        m4_install.verify_installed(current)
        before = running_identity()
        before_units = {name: show(name) for name in PRESERVED}
        need(all(item.get('ActiveState') == 'active' for item in before_units.values()),
             'PRESERVED_SERVICE_NOT_ACTIVE')
        with tempfile.TemporaryDirectory(prefix='management-upgrade-', dir='/var/lib/bridge-m4-install') as temp:
            database = database_snapshot(Path(temp))
            source = source_identity()
            if not restore_only:
                files = management_payload(current)
                desired, changed = plan(current, files)
                # Verify candidate bytes before stopping management listeners.
                for name in changed:
                    need(sha(files[name][0]) == desired[name]['sha256'], 'STAGING_HASH')
            stopped = False
            begun = False
            try:
                stop_management()
                stopped = True
                if restore_only:
                    restore()
                else:
                    begin(changed | {str(MANIFEST)})
                    begun = True
                    for name in sorted(changed):
                        target = Path(name)
                        need(not target.is_symlink(), 'INSTALL_LINK')
                        body, mode = files[name]
                        write(target, body, mode)
                    write(MANIFEST, (json.dumps({'schemaVersion': 1, 'files': desired},
                                                sort_keys=True)+'\n').encode(), 0o644)
                    commit()
                start_management()
                unchanged(before)
                need(database_snapshot(Path(temp)) == database, 'DATABASE_CHANGED')
                need(source_identity() == source, 'SOURCE_CHANGED')
                for name in PRESERVED:
                    need(show(name) == before_units[name], 'PRESERVED_SERVICE_CHANGED')
                verify_installed_dns(current)
                m4_install.verify_installed(json.loads(MANIFEST.read_text()))
                print(json.dumps({'managementUpgrade': 'RESTORED' if restore_only else 'PASS',
                                  'changedFiles': 0 if restore_only else len(changed),
                                  'daePid': before['dae']['MainPID']}, sort_keys=True))
            except BaseException:
                if stopped and not restore_only and begun:
                    try:
                        ctl('stop', *MANAGEMENT)
                        restore()
                        start_management()
                        unchanged(before)
                        need(database_snapshot(Path(temp)) == database, 'ROLLBACK_DATABASE_CHANGED')
                        m4_install.verify_installed(current)
                        print('{"managementUpgrade":"ROLLED_BACK"}', flush=True)
                    except BaseException:
                        print('{"managementUpgrade":"MANUAL_INTERVENTION_REQUIRED"}', flush=True)
                elif stopped and not begun:
                    start_management()
                raise


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    need(argv in ([], ['--restore']), 'ARGUMENTS_REJECTED')
    execute(restore_only=bool(argv))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': str(exc) if type(exc) is RuntimeError
                          else type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1)
