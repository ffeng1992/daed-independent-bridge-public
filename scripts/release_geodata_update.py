"""Bounded upstream SHA-256 geodata updater for the existing independent bridge.

No rule, official binary, official asset, database or installed-file manifest is
rewritten. A verified, immutable generation becomes active by one atomic symlink.
"""
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bridge_m4 import geodata

SOURCES = {
    'geosite.dat': ('v2fly/domain-list-community', 'dlc.dat'),
    'geoip.dat': ('v2fly/geoip', 'geoip.dat'),
}
RELEASE_LOCK = Path('/run/bridge-release.lock')
APPLY_LOCK = Path('/var/lib/daed-independent-bridge/apply.lock')
MAX_META = 1024 * 1024
MAX_SUM = 2048
SHA_LINE = re.compile(r'^([0-9a-fA-F]{64})  ([a-z0-9.-]+)\s*\Z')
TAG = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,69}\Z')


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


class HTTPS:
    def get(self, url, cap):
        require(url.startswith('https://'), 'GEODATA_HTTPS_REQUIRED')
        request = urllib.request.Request(url, headers={
            'User-Agent': 'independent-bridge-geodata/1.0',
            'Accept': 'application/octet-stream, application/vnd.github+json',
        })
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(cap + 1)
        require(0 < len(data) <= cap, 'GEODATA_RESPONSE_LIMIT')
        return data


def source_url(repository, tag, filename):
    require(repository in {value[0] for value in SOURCES.values()} and
            TAG.fullmatch(tag) is not None and '..' not in tag and
            filename in {'dlc.dat', 'geoip.dat', 'dlc.dat.sha256sum', 'geoip.dat.sha256sum'},
            'GEODATA_RELEASE_ASSET_REJECTED')
    return ('https://github.com/' + repository + '/releases/download/' +
            urllib.parse.quote(tag, safe='') + '/' + filename)


def metadata(https, name):
    repository, filename = SOURCES[name]
    remote = json.loads(https.get('https://api.github.com/repos/' + repository + '/releases/latest', MAX_META))
    require(type(remote) is dict and type(remote.get('tag_name')) is str and
            TAG.fullmatch(remote['tag_name']) is not None and '..' not in remote['tag_name'],
            'GEODATA_RELEASE_TAG')
    tag = remote['tag_name']
    assets = {a.get('name'): a for a in remote.get('assets', []) if type(a) is dict}
    for required in (filename, filename + '.sha256sum'):
        item = assets.get(required)
        require(type(item) is dict and item.get('browser_download_url') ==
                source_url(repository, tag, required), 'GEODATA_RELEASE_PROVENANCE')
    line = https.get(source_url(repository, tag, filename + '.sha256sum'), MAX_SUM)
    try:
        match = SHA_LINE.fullmatch(line.decode('ascii').strip())
    except UnicodeError:
        match = None
    require(match is not None and match[2] == filename, 'GEODATA_SHA256_FORMAT')
    return {'repository': repository, 'tag': tag, 'filename': filename,
            'sha256': match[1].lower(), 'url': source_url(repository, tag, filename)}


@contextlib.contextmanager
def exclusive(paths=(RELEASE_LOCK, APPLY_LOCK)):
    opened = []
    try:
        for path in paths:
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            opened.append(fd)
            st = os.fstat(fd)
            require(st.st_uid == 0 and st.st_nlink == 1 and not (st.st_mode & 0o022),
                    'GEODATA_LOCK_AUTHORITY')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('GEODATA_UPDATE_BUSY') from None
        yield
    finally:
        for fd in reversed(opened):
            os.close(fd)


def provision(root, *, uid=0):
    root = Path(root)
    if not root.exists():
        root.mkdir(mode=0o700)
    else:
        geodata.check_directory(root, uid)
    versions = root / 'versions'
    if not versions.exists():
        versions.mkdir(mode=0o700)
    geodata.check_directory(versions, uid)
    geodata.syncdir(root)
    return versions


def present(root, official, *, uid=0):
    folder = geodata.selected_dir(root, official, uid=uid)
    return {name: geodata.verify_file(folder / name, uid=uid, max_size=geodata.LIMITS[name])
            for name in geodata.DATASETS}


def publish(root, content, remote, *, uid=0):
    versions = provision(root, uid=uid)
    record = {'schemaVersion': 1, 'datasets': {
        name: {'sha256': geodata.sha(content[name]), 'size': len(content[name]),
               'repository': remote[name]['repository'], 'tag': remote[name]['tag']}
        for name in geodata.DATASETS}}
    blob = geodata.canonical(record)
    identity = geodata.sha(blob)
    destination = versions / identity
    if destination.exists():
        # Reuse only if the complete old immutable generation matches.
        pointer = Path(root) / 'current'
        require(not destination.is_symlink(), 'GEODATA_GENERATION_LINK')
        geodata.check_directory(destination, uid)
        require(geodata.verify_file(destination / 'manifest.json', uid=uid) == blob,
                'GEODATA_EXISTING_GENERATION')
        for name, data in content.items():
            require(geodata.verify_file(destination / name, uid=uid) == data,
                    'GEODATA_EXISTING_DATA')
        return identity, destination
    stage = Path(tempfile.mkdtemp(prefix='.incoming-', dir=versions))
    stage.chmod(0o700)
    try:
        for name in geodata.DATASETS:
            require(0 < len(content[name]) <= geodata.LIMITS[name], 'GEODATA_SIZE_LIMIT')
            fd = os.open(stage / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
            with os.fdopen(fd, 'wb') as output:
                output.write(content[name]); output.flush(); os.fsync(output.fileno())
            (stage / name).chmod(0o444)
        fd = os.open(stage / 'manifest.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, 'wb') as output:
            output.write(blob); output.flush(); os.fsync(output.fileno())
        (stage / 'manifest.json').chmod(0o400)
        geodata.syncdir(stage)
        os.rename(stage, destination)
        geodata.syncdir(versions)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    # A generation is fully validated before switching the public pointer.
    require(geodata.verify_file(destination / 'manifest.json', uid=uid) == blob,
            'GEODATA_MANIFEST_READBACK')
    return identity, destination


def record(root, value):
    root = Path(root)
    provision(root)
    # Preserve the last *successful update* even after NO_CHANGE or a failed check.
    try:
        history = json.loads((root / 'last-check.json').read_text())
        if history.get('updatedAt') and not value.get('updatedAt'):
            value['updatedAt'] = history['updatedAt']
    except (OSError, ValueError, TypeError):
        pass
    # Status metadata is not part of the installed-file manifest.
    geodata.atomic_bytes(root / 'last-check.json', geodata.canonical(value), mode=0o644)


def trim_generations(root, keep):
    """Bound disk growth while retaining the active and rollback generations."""
    versions = Path(root) / 'versions'
    entries = []
    for item in versions.iterdir():
        if not re.fullmatch(r'[a-f0-9]{64}', item.name) or item.is_symlink() or not item.is_dir():
            continue
        entries.append(item)
    entries.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    survivors = set(keep) | {item.name for item in entries[:3]}
    for item in entries:
        if item.name not in survivors:
            shutil.rmtree(item)
    geodata.syncdir(versions)


def system_state():
    from bridge_m4.validation import DAE_ENV
    from bridge_m4.dns_sync_runtime import read_status
    state, expected = read_status()
    require(state.get('state') == 'running' and state.get('identityVerified') is True and
            state.get('configSha256') == expected and bool(state.get('activeBundle')),
            'GEODATA_DAE_NOT_HEALTHY')
    # Do not silently adopt a DAE started against another manually updated asset
    # location. That must be reconciled before enabling this updater.
    pid = int(state.get('MainPID', 0))
    require(pid > 0, 'GEODATA_DAE_PID_UNKNOWN')
    environment = (Path('/proc') / str(pid) / 'environ').read_bytes()
    baseline = Path(DAE_ENV['DAE_LOCATION_ASSET'])
    expected_path = geodata.selected_dir(official=baseline)
    require((b'\x00DAE_LOCATION_ASSET=' + os.fsencode(expected_path) + b'\x00') in
            (b'\x00' + environment + b'\x00'),
            'GEODATA_EXISTING_DAE_ASSET_PATH_MISMATCH')
    return state


def policy_dns_active():
    for unit in ('bridge-policy-dns.service', 'dae-policy-dns.service'):
        result = subprocess.run(['/usr/bin/systemctl', 'show', unit,
                                 '--property=ActiveState', '--value'],
                                capture_output=True, text=True, timeout=5, check=True)
        state = result.stdout.strip()
        require(state in {'active', 'inactive', 'failed', 'activating', 'deactivating'},
                'GEODATA_POLICY_DNS_STATE_UNKNOWN')
        if state != 'inactive':
            require(state == 'active', 'GEODATA_POLICY_DNS_NOT_HEALTHY')
            return True
    return False


def verify_staging(directory):
    from bridge_m4.authority import policy
    from bridge_m4.validation import validate
    from bridge_m4.release_policy import generate
    status = system_state()
    active = status['activeBundle']
    bundle = Path('/var/lib/daed-independent-bridge/versions') / active
    candidate = bundle / 'candidate.dae'
    validate(candidate, policy()['validateBinarySha256'], assets_override=directory)
    # Validate policy DNS categories only when that existing consumer is active.
    # Retired DNS services are never re-enabled by a geodata check.
    if not policy_dns_active():
        return
    configuration = json.loads((bundle / 'normalized-ir.json').read_text())
    routing = ''.join(item['text'] for item in configuration['routing']['tokens'])
    settings = json.loads(Path('/etc/daed-independent-bridge/release.json').read_text())
    generate(routing, settings['providers'], Path(directory) / 'geosite.dat')


def restart_and_wait(expected, asset_path, *, attempt_timeout=85):
    subprocess.run(['/usr/bin/systemctl', 'restart', 'dae.service'],
                   check=True, capture_output=True, timeout=55)
    end = time.monotonic() + attempt_timeout
    while time.monotonic() < end:
        try:
            state = system_state()
            same_bundle = state.get('activeBundle') == expected.get('activeBundle')
            same_config = state.get('configSha256') == expected.get('configSha256')
            new_instance = state.get('InvocationID') != expected.get('InvocationID')
            pid = int(state.get('MainPID', 0))
            if same_bundle and same_config and new_instance and pid > 0:
                # Prove the new DAE process received the intended geodata directory.
                environment = (Path('/proc') / str(pid) / 'environ').read_bytes()
                require(b'DAE_LOCATION_ASSET=' + os.fsencode(asset_path) + b'\x00' in b'\x00' + environment + b'\x00',
                        'GEODATA_DAE_ENVIRONMENT_MISMATCH')
                return state
        except (OSError, ValueError, RuntimeError):
            pass
        time.sleep(1)
    raise RuntimeError('GEODATA_DAE_RESTART_NOT_VERIFIED')


def once(*, root=geodata.BASE, official=None,
         client=None, owner=0, check_health=None, validate_stage=None,
         restart=None, update_record=True):
    """Purely bounded update transaction; dependencies may be replaced in isolated tests."""
    if official is None:
        from bridge_m4.validation import DAE_ENV
        official = Path(DAE_ENV['DAE_LOCATION_ASSET'])
    root, official = Path(root), Path(official)
    client = client or HTTPS()
    check_health = check_health or system_state
    validate_stage = validate_stage or verify_staging
    restart = restart or restart_and_wait
    begin = now_utc()
    previous = None
    switched = False
    before = None
    remote = {}
    outcome = {'checkedAt': begin, 'result': 'CHECK_FAILED'}
    try:
        provision(root, uid=owner)
        # Precondition before downloading: no update during an apply, outage or setup.
        before = check_health()
        previous = geodata.current_id(root)
        originals = present(root, official, uid=owner)
        old_hashes = {name: geodata.sha(originals[name]) for name in geodata.DATASETS}
        for name in geodata.DATASETS:
            remote[name] = metadata(client, name)
        changed = [name for name in geodata.DATASETS if remote[name]['sha256'] != old_hashes[name]]
        outcome['remote'] = {name: {'tag': item['tag'], 'sha256': item['sha256']}
                             for name, item in remote.items()}
        if not changed:
            outcome.update(result='NO_CHANGE', assets=old_hashes,
                           message='两份数据都已是最新版，未下载DAT，未重启DAE')
            return outcome
        # Existing bytes are comparison/rollback data, not an old-release gate.
        latest = dict(originals)
        for name in changed:
            expected = remote[name]['sha256']
            blob = client.get(remote[name]['url'], geodata.LIMITS[name])
            require(geodata.sha(blob) == expected, 'GEODATA_UPSTREAM_SHA256_MISMATCH')
            latest[name] = blob
        identity, folder = publish(root, latest, remote, uid=owner)
        validate_stage(folder)
        # Recheck that no other controlled operation changed the active configuration.
        pre_switch = check_health()
        require(pre_switch.get('activeBundle') == before.get('activeBundle') and
                pre_switch.get('configSha256') == before.get('configSha256'),
                'GEODATA_ACTIVE_CONFIG_CHANGED')
        geodata.switch(root, identity, uid=owner)
        switched = True
        restart(before, folder)
        current, _ = geodata.generation(root, uid=owner)
        require(current == folder, 'GEODATA_SWITCH_DRIFT')
        outcome.update(result='UPDATED', updatedAt=now_utc(),
                       changed=changed, generation=identity,
                       assets={name: geodata.sha(latest[name]) for name in geodata.DATASETS},
                       message='已验证并启用新版DAT，DAE重启一次')
        # Keep previous/active generations available for safe recovery.
        try:
            trim_generations(root, {identity, previous} - {None})
        except (OSError, RuntimeError):
            pass  # Cleanup cannot invalidate an already healthy data-plane switch.
        return outcome
    except Exception as exc:
        error_code = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        outcome.update(result='CHECK_FAILED', error=error_code)
        if switched:
            try:
                geodata.switch(root, previous, uid=owner)
                rollback_dir = geodata.selected_dir(root, official, uid=owner)
                restart(before, rollback_dir)
                outcome.update(result='ROLLED_BACK',
                               message='新版启动异常，已恢复旧数据并重新启动DAE')
            except Exception as rollback_error:
                outcome.update(result='ROLLBACK_FAILED',
                               rollbackError=type(rollback_error).__name__)
        return outcome
    finally:
        if update_record:
            try:
                record(root, outcome)
            except Exception:
                # Status logging must never mask the actual system outcome.
                pass


def print_status(root=geodata.BASE, official=None):
    if official is None:
        from bridge_m4.validation import DAE_ENV
        official = Path(DAE_ENV['DAE_LOCATION_ASSET'])
    try:
        data = json.loads((Path(root) / 'last-check.json').read_text())
    except FileNotFoundError:
        data = {'result': 'NOT_CHECKED'}
    folder, version = geodata.generation(root)
    summary = {'result': data.get('result'), 'checkedAt': data.get('checkedAt'),
               'updatedAt': data.get('updatedAt'), 'generation': geodata.current_id(root),
               'datasets': version['datasets'] if version else
               {name: {'sha256': geodata.sha((Path(official) / name).read_bytes()), 'tag': '初始文件'}
                for name in geodata.DATASETS},
               'lastError': data.get('error')}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    require(os.geteuid() == 0, 'GEODATA_ROOT_REQUIRED')
    require(argv in (['check'], ['status']), 'GEODATA_ACTION_REJECTED')
    if argv == ['status']:
        print_status()
        return 0
    with exclusive():
        result = once()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # A successful rollback still means the update failed. Surface this in systemd.
    return 0 if result['result'] in {'UPDATED', 'NO_CHANGE'} else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'result': 'CHECK_FAILED', 'error': str(error) if type(error) is RuntimeError else type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
