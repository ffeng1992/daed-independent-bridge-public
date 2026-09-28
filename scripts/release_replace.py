"""One bounded replacement of the verified 830-file Shanghai management install.

The existing DAE process, official binaries, dnsdist, policy DNS, ingress sync,
and both DNS-sync implementations are deliberately outside this transaction.
This is not an adoption path for arbitrary pre-existing installations.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

from scripts import m4_install
from scripts.m4_install_transaction import begin, commit, exclusive, restore, write
from scripts.release_frontend import payload as frontend_payload
from scripts.release_prepare import prepare
from scripts.release_setup import bridge_credentials

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path('/etc/daed-independent-bridge/install.json')
DB = Path('/var/lib/bridge-daed/wing.db')
STATE = Path('/var/lib/bridge-m4-install')
MANAGEMENT = ('daed-web.service', 'bridge-graphql.service',
              'independent-bridge.service', 'bridge-attestor.service',
              'bridge-helper.socket', 'daed-api.service')
HELPER = 'bridge-helper.service'
TIMERS = ('independent-dns-sync.timer', 'independent-policy-sync.timer')
SYNC_RUNS = ('independent-dns-sync.service', 'independent-policy-sync.service')
PRESERVED = ('dae.service', 'dnsdist.service', 'dae-policy-dns.service',
             'dae-ingress-sync.timer')
ADDED = {
    '/opt/bridge/bridge_m4/dnsdist_control.py',
    '/opt/bridge/bridge_m4/graphql_config.py',
    '/opt/bridge/bridge_m4/release_dns.py',
    '/opt/bridge/bridge_m4/release_policy.py',
}
CHANGED = {
    '/etc/systemd/system/daed-api.service',
    '/opt/bridge/bridge_m4/attestor.py',
    '/opt/bridge/bridge_m4/auth.py',
    '/opt/bridge/bridge_m4/convert.py',
    '/opt/bridge/bridge_m4/diagnostics.py',
    '/opt/bridge/bridge_m4/extensions.py',
    '/opt/bridge/bridge_m4/graphql_runtime.py',
    '/opt/bridge/bridge_m4/official_web.py',
    '/opt/bridge/bridge_m4/runtime.py',
    '/opt/bridge/bridge_m4/web.py',
    '/opt/bridge/bridge_m4/web/app.js',
    '/opt/bridge/bridge_m4/web/index.html',
}
DNS_FILES = (
    '/etc/dae-dns-repair/sync_policy_independent.py',
    '/etc/dae-dns-repair/build_dns.py',
    '/etc/dae-dns-repair/policy-dns.conf',
    '/etc/systemd/system/independent-dns-sync.service',
    '/etc/systemd/system/independent-dns-sync.timer',
    '/etc/systemd/system/independent-policy-sync.service',
    '/etc/systemd/system/independent-policy-sync.timer',
    '/etc/systemd/system/dae-policy-dns.service',
    '/etc/systemd/system/dae-ingress-sync.service',
    '/etc/systemd/system/dae-ingress-sync.timer',
    '/etc/dnsdist/dnsdist.conf',
)


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def ctl(*args):
    return subprocess.run(['/usr/bin/systemctl', *args], check=True,
                          capture_output=True, timeout=90)


def show(unit):
    raw = ctl('show', unit, '--property=ActiveState,SubState,MainPID,InvocationID,NRestarts').stdout.decode()
    return dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)


def file_identity(name):
    path = Path(name)
    if not path.exists():
        return None
    item = path.lstat()
    need(stat.S_ISREG(item.st_mode) and item.st_nlink == 1 and not path.is_symlink(),
         'PRESERVED_FILE_IDENTITY:' + str(name))
    return (sha(path.read_bytes()), item.st_uid, item.st_gid, stat.S_IMODE(item.st_mode))


def database_snapshot(directory):
    need(DB.is_file() and not DB.is_symlink(), 'DATABASE_IDENTITY')
    # sqlite3.Connection.backup() into an existing destination can preserve
    # destination page layout/free-list bytes. Compare fresh complete backups,
    # never two successive writes to one SQLite file.
    fd, name = tempfile.mkstemp(prefix='database-check-', suffix='.sqlite', dir=directory)
    os.close(fd)
    path = Path(name)
    source = sqlite3.connect('file:' + str(DB) + '?mode=ro', uri=True)
    target = sqlite3.connect(str(path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    path.chmod(0o600)
    check = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
    try:
        need(check.execute('pragma integrity_check').fetchone()[0] == 'ok', 'DATABASE_INTEGRITY')
    finally:
        check.close()
    return sha(path.read_bytes())


def source_identity():
    from bridge_m4.collect import collect
    from bridge_m1.collect import HTTPReader
    token = Path('/etc/daed-independent-bridge/backend.token').read_text().strip()
    source, proof = collect(HTTPReader('http://127.0.0.1:2024/graphql', token))
    need(proof['beforeSha256'] == proof['afterSha256'], 'SOURCE_UNSTABLE')
    return proof['afterSha256']


def payload_and_manifest(old):
    prepare(ROOT)
    files = m4_install.payload()
    files.update(frontend_payload(ROOT))
    files['/etc/systemd/system/daed-web.service'] = (
        (ROOT/'deployment/release/units/daed-web.service').read_bytes(), 0o644)
    desired = {name: {'sha256': sha(body), 'mode': mode}
               for name, (body, mode) in sorted(files.items())}
    previous = old['files']
    need(len(previous) == 830 and len(desired) == 834, 'INSTALL_LAYOUT_UNRECOGNIZED')
    need(set(desired) - set(previous) == ADDED and
         set(previous) - set(desired) == set(), 'INSTALL_LAYOUT_UNRECOGNIZED')
    changed = {name for name in previous if previous[name] != desired[name]}
    need(changed == CHANGED, 'CANDIDATE_DIFF_UNEXPECTED')
    for name in desired:
        if name.startswith(('/opt/bridge-official/', '/opt/bridge-service/')):
            need(desired[name] == previous[name], 'OFFICIAL_FILE_CHANGE_REJECTED')
    return files, desired


def stage(files, desired, directory):
    staged = directory / 'payload'
    staged.mkdir(mode=0o700)
    for index, name in enumerate(sorted(CHANGED | ADDED)):
        body, mode = files[name]
        target = staged / str(index)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        need(file_identity(target)[0] == desired[name]['sha256'], 'STAGED_HASH')
    fd = os.open(staged, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return staged


def verify_management():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if all(show(name).get('ActiveState') == 'active' for name in MANAGEMENT):
            break
        time.sleep(1)
    need(all(show(name).get('ActiveState') == 'active' for name in MANAGEMENT),
         'MANAGEMENT_START_FAILED')
    from scripts.release_health import web_status
    config = json.loads(Path('/etc/daed-independent-bridge/web.json').read_text())
    token = Path('/etc/daed-independent-bridge/bridge-login.token').read_text().strip()
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            result = web_status(config, token)
            need(result.get('state') == 'running' and result.get('identityVerified') is True,
                 'BRIDGE_STATUS_IDENTITY')
            return result
        except (OSError, ValueError, RuntimeError):
            time.sleep(1)
    raise RuntimeError('BRIDGE_WEB_HEALTH_FAILED')


def verify_dns():
    from scripts.release_health import dns
    from bridge_m4.dns_sync_runtime import Backends, read_status
    from bridge_m4.dns_sync import decide
    status, expected = read_status()
    need(status.get('state') == 'running' and status.get('identityVerified') is True and
         status.get('configSha256') == expected, 'DAE_IDENTITY')
    backends = Backends().states()
    need(backends == {'DAE': 'UP', 'DIRECT': 'DOWN'} and
         decide(status, expected, backends)['consistent'], 'DNS_SYNC_STATUS')
    health = json.loads(Path('/etc/daed-independent-bridge/health.json').read_text())
    need(set(health) == {'lanAddress', 'dnsName'}, 'HEALTH_CONFIG_SCHEMA')
    for address, port in ((health['lanAddress'], 53), ('127.0.0.1', 5353)):
        for tcp in (False, True):
            dns(address, port, health['dnsName'], tcp)
    return status


def preserved_services(before):
    now = {unit: show(unit) for unit in PRESERVED}
    need(all(value.get('ActiveState') == 'active' for value in now.values()),
         'PRESERVED_SERVICE_STOPPED')
    # Only DAE must retain its exact process and invocation identity. An
    # independent, pre-existing policy DNS timer may naturally refresh 5534.
    for field in ('MainPID', 'InvocationID', 'NRestarts'):
        need(now['dae.service'].get(field) == before['dae.service'].get(field),
             'DAE_PROCESS_CHANGED')


def wait_sync_idle():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        states = [show(name).get('ActiveState') for name in SYNC_RUNS]
        if all(state == 'inactive' for state in states):
            return
        need(all(state in {'inactive', 'activating'} for state in states),
             'DNS_SYNC_NOT_HEALTHY')
        time.sleep(1)
    raise RuntimeError('DNS_SYNC_BUSY')


def restore_management():
    ctl('stop', *MANAGEMENT, HELPER)
    restore()
    ctl('daemon-reload')
    ctl('start', *reversed(MANAGEMENT))
    ctl('start', *TIMERS)


def execute():
    need(os.geteuid() == 0 and Path('/run/systemd/system').is_dir(), 'DEBIAN_SYSTEMD_ROOT_REQUIRED')
    need(MANIFEST.exists(), 'EXISTING_MANIFEST_REQUIRED')
    with open('/run/bridge-release.lock', 'a') as release_lock, exclusive():
        fcntl.flock(release_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = json.loads(MANIFEST.read_text())
        m4_install.verify_installed(old)
        before = {unit: show(unit) for unit in PRESERVED}
        need(all(v.get('ActiveState') == 'active' for v in before.values()), 'PRESERVED_SERVICE_NOT_ACTIVE')
        need(all(show(unit).get('ActiveState') == 'active' for unit in MANAGEMENT + TIMERS),
             'MANAGEMENT_BASELINE_NOT_ACTIVE')
        original = {name: file_identity(name) for name in DNS_FILES}
        need(all(value is not None for value in original.values()), 'DNS_DEPENDENCY_MISSING')
        need(file_identity('/opt/bridge-service/dae') is not None, 'DAE_BINARY_MISSING')
        files, desired = payload_and_manifest(old)
        sys.path.insert(0, str(ROOT/'out/m4-vendor'))
        STATE.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='replace-', dir=STATE) as directory_name:
            directory = Path(directory_name)
            before_db = database_snapshot(directory)
            before_source = source_identity()
            before_status = verify_dns()
            need(str(before_status.get('MainPID')) == before['dae.service']['MainPID'] and
                 before_status.get('InvocationID') == before['dae.service']['InvocationID'], 'DAE_BASELINE_IDENTITY')
            stage(files, desired, directory)
            # Official daed, DAE, Web assets and DNS are deliberately byte-identical.
            need(all(file_identity(name) == original[name] for name in DNS_FILES), 'DNS_FILE_DRIFT')
            bridge_credentials()  # Separate new login secret; never changes daed accounts.
            login_identity = file_identity('/etc/daed-independent-bridge/bridge-login.token')
            need(login_identity is not None and login_identity[1:] ==
                 (0, pwd.getpwnam('independent-bridge').pw_gid, 0o640),
                 'BRIDGE_CREDENTIAL_MODE')
            print(json.dumps({'STAGING_PASS': True, 'changed': len(CHANGED), 'added': len(ADDED)}, sort_keys=True), flush=True)
            begun = False
            try:
                # Briefly pause timer triggers; their code, state and DNS listeners remain untouched.
                ctl('stop', *TIMERS)
                wait_sync_idle()
                ctl('stop', *MANAGEMENT, HELPER)
                begin(CHANGED | ADDED | {str(MANIFEST)})
                begun = True
                for name in sorted(CHANGED | ADDED):
                    body, mode = files[name]
                    target = Path(name)
                    need(not target.is_symlink(), 'INSTALL_LINK')
                    write(target, body, mode)
                record = {'schemaVersion': 1, 'files': desired}
                write(MANIFEST, (json.dumps(record, sort_keys=True) + '\n').encode(), 0o644)
                ctl('daemon-reload')
                ctl('start', *reversed(MANAGEMENT))
                web = verify_management()
                ctl('start', *TIMERS)
                after_db = database_snapshot(directory)
                need(before_db == after_db, 'DATABASE_CHANGED')
                need(source_identity() == before_source, 'SOURCE_CHANGED')
                after_status = verify_dns()
                need(after_status.get('activeBundle') == before_status.get('activeBundle') and
                     after_status.get('configSha256') == before_status.get('configSha256'),
                     'BUNDLE_CHANGED')
                need(web.get('MainPID') == after_status.get('MainPID'), 'WEB_DAE_IDENTITY')
                need(all(file_identity(name) == original[name] for name in DNS_FILES), 'DNS_FILE_CHANGED')
                preserved_services(before)
                m4_install.verify_installed(record)
                commit()
                print(json.dumps({'CUTOVER_RESULT': 'PASS', 'DATABASE_UNCHANGED': True,
                                  'DNS_DATAPLANE': 'PASS', 'DAE_PID_BEFORE_AFTER':
                                  [before['dae.service']['MainPID'], show('dae.service')['MainPID']],
                                  'FINAL_RESULT': 'PASS'}, sort_keys=True))
            except BaseException:
                if begun:
                    try:
                        restore_management()
                        need(database_snapshot(directory) == before_db, 'ROLLBACK_DATABASE_CHANGED')
                        need(source_identity() == before_source, 'ROLLBACK_SOURCE_CHANGED')
                        need(all(file_identity(name) == original[name] for name in DNS_FILES), 'ROLLBACK_DNS_CHANGED')
                        preserved_services(before)
                        need(all(show(name).get('ActiveState') == 'active' for name in MANAGEMENT),
                             'ROLLBACK_MANAGEMENT_FAILED')
                        verify_dns()
                        m4_install.verify_installed(old)
                        print('{"FINAL_RESULT":"ROLLED_BACK"}', flush=True)
                    except BaseException:
                        print('{"FINAL_RESULT":"MANUAL_INTERVENTION_REQUIRED"}', flush=True)
                else:
                    ctl('start', *reversed(MANAGEMENT))
                    ctl('start', *TIMERS)
                raise


def main(argv=None):
    need(not argv, 'ARGUMENTS_REJECTED')
    execute()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        # Never print subprocess output, credentials, SQL data or candidate config.
        print(json.dumps({'error': str(exc) if type(exc) is RuntimeError else type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1)
