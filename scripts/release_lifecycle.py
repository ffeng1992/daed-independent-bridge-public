"""Fixed lifecycle commands; no production discovery or migration workflow."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CFG = Path('/etc/daed-independent-bridge')
MANIFEST = CFG / 'install.json'
CORE = ('daed-api.service', 'bridge-helper.socket', 'bridge-attestor.service',
        'independent-bridge.service', 'dae.service', 'daed-web.service')
DNS = ('bridge-policy-dns.service', 'bridge-lan-dns.service')
TIMERS = ('independent-dns-sync.timer', 'independent-policy-sync.timer')
STOP = (*TIMERS, 'independent-policy-sync.service', 'independent-dns-sync.service',
        'daed-web.service', 'dae.service', 'independent-bridge.service', 'bridge-attestor.service',
        'bridge-helper.socket', 'bridge-helper.service', 'daed-api.service', *DNS)
DATA = (CFG, Path('/var/lib/bridge-daed'), Path('/var/lib/bridge-m4-client'),
        Path('/var/lib/bridge-m4-attestation'), Path('/var/lib/daed-independent-bridge'),
        Path('/var/lib/bridge-m4-install'), Path('/opt/bridge-official/assets'))
REQUIRED_CONFIG = ('web.json', 'tls.crt', 'tls.key', 'attestor.token', 'health.json')


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def run(args, **kwargs):
    # Captured stderr can contain service/configuration details: never echo it.
    return subprocess.run(args, check=True, capture_output=True, timeout=180, **kwargs)


def ctl(*args):
    return run(['/usr/bin/systemctl', *args])


def platform_check():
    need(os.geteuid() == 0, 'ROOT_REQUIRED')
    values = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    need(values.get('ID', '').strip('"') == 'debian' and
         values.get('VERSION_ID', '').strip('"') == '13' and
         platform.machine() == 'x86_64' and sys.version_info[:2] == (3, 13),
         'DEBIAN_13_AMD64_PYTHON_313_REQUIRED')
    need(Path('/run/systemd/system').is_dir(), 'SYSTEMD_PID1_REQUIRED')


def config_check():
    for name in (*REQUIRED_CONFIG, 'release.json', 'lan-dns.conf', 'policy-dns.conf'):
        p = CFG / name
        need(p.is_file() and not p.is_symlink(), 'INITIAL_CONFIGURATION_REQUIRED:' + name)
        st = p.stat()
        need(st.st_uid == 0 and not stat.S_IMODE(st.st_mode) & 0o022,
             'CONFIGURATION_PERMISSIONS:' + name)
    need(Path('/var/lib/bridge-m4-client/extensions/current').is_file(), 'INITIAL_EXTENSIONS_REQUIRED')
    need(Path('/var/lib/daed-independent-bridge/current').is_symlink(), 'VERIFIED_INITIAL_BUNDLE_REQUIRED')


def packages():
    import importlib.util
    if all(shutil.which(x) for x in ('dnsdist','dig','openssl','ip','nginx')) and importlib.util.find_spec('pip'):
        return
    nginx_before = subprocess.run(['dpkg-query','-W','-f=${Status}','nginx'],capture_output=True).returncode==0
    before = subprocess.run(['dpkg-query', '-W', '-f=${Status}', 'dnsdist'], capture_output=True).returncode == 0
    run(['apt-get', 'update', '-qq'])
    subprocess.run(['apt-get', 'install', '-y', '-qq', 'python3-pip', 'bind9-dnsutils', 'dnsdist',
                    'openssl', 'iproute2', 'ca-certificates', 'nginx'], check=True, capture_output=True,
                   timeout=600, env=dict(os.environ, DEBIAN_FRONTEND= 'noninteractive'))
    if not nginx_before:ctl('disable','--now','nginx.service')
    if not before:
        ctl('disable', '--now', 'dnsdist.service')


def inactive_unit(name, output):
    fields = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
    # Socket units have no MainPID property; only service units own a process.
    need(fields.get('ActiveState') == 'inactive' and
         (name.endswith('.socket') or fields.get('MainPID') == '0'),
         'UNMANAGED_ACTIVE_SERVICE:' + name)


def ready_payload():
    from scripts.m4_install import payload
    # Downloads are separately hash-verified; no service is stopped before this.
    from scripts.release_prepare import prepare
    prepare(ROOT)
    return payload(release_profile=True)


def health():
    from scripts.release_health import check
    check()


def wait_for_dataplane():
    # Type=simple start returns before official DAE finishes loading BPF/DNS.
    sys.path[:0] = ['/opt/bridge', '/opt/bridge/vendor']
    from bridge_m4.dns_sync_runtime import read_status
    deadline = time.monotonic() + 60
    while True:
        try:
            status, expected = read_status()
            if (status.get('state') == 'running' and status.get('identityVerified') is True
                    and expected and status.get('configSha256') == expected):
                return
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
            pass  # Bounded startup observation only; no service retry or success fallback.
        need(time.monotonic() < deadline, 'DATAPLANE_STARTUP_TIMEOUT')
        time.sleep(1)


def start():
    ctl('daemon-reload')
    ctl('enable', *CORE, *DNS, *TIMERS)
    ctl('start', *DNS)
    ctl('start', *CORE)
    wait_for_dataplane()
    ctl('start', *TIMERS)


def stop():
    # Stop trigger sources before consumers. systemd marks an interrupted
    # oneshot as failed on SIGTERM even for an explicit administrative stop.
    ctl('stop', *TIMERS)
    oneshots = ('independent-policy-sync.service', 'independent-dns-sync.service')
    ctl('stop', *oneshots)
    stopping=tuple(name for name in STOP if name not in TIMERS + oneshots and
                   (name!='daed-web.service' or Path('/etc/systemd/system/daed-web.service').exists()))
    ctl('stop', *stopping)
    # Official daed can exit 1 during a requested SIGTERM. This is an
    # administrative teardown, not a health result; verify absence of every
    # owned process before clearing its failed status and replacing files.
    for name in STOP:
        if not name.endswith('.service') or (name=='daed-web.service' and name not in stopping):continue
        fields = dict(line.split('=', 1) for line in
                      ctl('show', name, '--property=ActiveState,MainPID').stdout.decode().splitlines() if '=' in line)
        need(fields.get('MainPID') == '0' and fields.get('ActiveState') in {'inactive', 'failed'}, 'SERVICE_STOP_FAILED:' + name)
        if fields['ActiveState'] == 'failed':ctl('reset-failed', name)


def same_payload(files, record):
    return record['files'] == {name: {'sha256': hashlib.sha256(body).hexdigest(), 'mode': mode}
                               for name, (body, mode) in files.items()}


def purge():
    # Fixed project-owned paths only. Shared DNS infrastructure is never removed.
    for p in DATA:
        need(not p.is_symlink(), 'PURGE_SYMLINK_REJECTED')
    for p in DATA:
        if p.exists():
            shutil.rmtree(p)


def execute(action, args):
    if action == 'health-check':
        health()
        return
    if action == 'uninstall':
        need(not args.purge or args.confirm_purge == 'DELETE-INDEPENDENT-BRIDGE',
             'PURGE_REQUIRES_EXPLICIT_CONFIRMATION')
        if MANIFEST.exists():
            from scripts import m4_install
            record = json.loads(MANIFEST.read_text())
            m4_install.verify_installed(record)
            stop()
            # Existing installer removes tracked program files only. Geodata is
            # explicitly retained by the release lifecycle option.
            m4_install.uninstall(preserve_assets=True)
        if args.purge:
            from scripts.m4_install import quiescent
            quiescent()
            purge()
        print(json.dumps({'uninstalled': True, 'persistentDataRetained': not args.purge}))
        return
    from scripts import m4_install
    record = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None
    need(action != 'upgrade' or record is not None, 'UPGRADE_REQUIRES_INSTALLATION')
    fresh = not (CFG / 'release.json').exists()
    if fresh:
        need(record is None and not Path('/var/lib/bridge-daed').exists(), 'EXISTING_CONFIGURATION_REFUSED')
        from scripts.release_setup import settings
        value = settings(args.settings)
        need(Path('/sys/class/net', value['lanInterface']).exists(), 'LAN_INTERFACE_NOT_FOUND')
        # Refuse a foreign installation instead of adopting databases/DAE.
        for name in CORE + DNS:
            result = ctl('show', name, '--property=ActiveState,MainPID').stdout.decode()
            inactive_unit(name, result)
    else:
        config_check()
    packages()
    files = ready_payload()
    if record:
        m4_install.verify_installed(record)
    if action == 'install' and record:
        need(same_payload(files, record), 'ALREADY_INSTALLED_DIFFERENT_VERSION_USE_UPGRADE')
        health()
        print('{"alreadyInstalled":true}')
        return
    if record:
        stop()
    m4_install.install(upgrade=record is not None, preserve_assets=True, release_profile=True)
    if fresh:
        from scripts.release_setup import configure, initialize, apply_initial
        configure(value)
        ctl('start', *DNS, 'daed-api.service')
        initialize()
        ctl('start', 'bridge-helper.socket', 'bridge-attestor.service', 'independent-bridge.service')
        apply_initial()
    start()
    # Synchronize once now; do not mistake an unexpired timer for healthy DNS.
    ctl('start', 'independent-dns-sync.service', 'independent-policy-sync.service')
    health()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('install', 'upgrade', 'uninstall', 'health-check'))
    p.add_argument('--settings', help='First-install network settings JSON (no credentials)')
    p.add_argument('--purge', action='store_true', help='Delete fixed project-owned persistent data')
    p.add_argument('--confirm-purge', choices=('DELETE-INDEPENDENT-BRIDGE',))
    args = p.parse_args(argv)
    need(args.action == 'uninstall' or not (args.purge or args.confirm_purge), 'UNINSTALL_OPTION_ONLY')
    platform_check()
    with open('/run/bridge-release.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute(args.action, args)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        # No traceback, subprocess output, token or configuration serialization.
        import traceback
        detail = {'passed': False, 'error': str(exc) if type(exc) is RuntimeError else type(exc).__name__,
                  'frames': [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                             for f in traceback.extract_tb(exc.__traceback__)[-4:]]}
        if isinstance(exc, subprocess.CalledProcessError):
            detail.update(command=Path(exc.cmd[0]).name, exitCode=exc.returncode)
        print(json.dumps(detail), file=sys.stderr)
        raise SystemExit(1)
