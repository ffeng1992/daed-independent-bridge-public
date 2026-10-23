"""Repeatable, explicit management-source plan; official binaries are out of scope.

Default is --plan. --apply-plan requires the exact reviewed plan digest and
rebuilds the plan from verified current inventory before stopping any service.
No dependency downloads, DNS configuration generation, database restoration,
service enablement, DAT updates or DAE restart are performed here.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
INSTALL = Path('/etc/daed-independent-bridge/install.json')
LAYOUT = Path('/etc/daed-independent-bridge/layout.json')
from scripts.management_payload import eligible, generate as generate_package, verify as verify_package
MANAGEMENT = ('bridge-helper.socket', 'bridge-helper.service', 'bridge-attestor.service',
              'independent-bridge.service', 'bridge-graphql.service', 'daed-web.service')
TIMERS = ('bridge-management-recovery.timer', 'bridge-geodata-update.timer',
          'independent-dns-sync.timer', 'independent-policy-sync.timer')


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _source(root, name):
    path = Path(root) / name
    need(not Path(name).is_absolute() and '..' not in Path(name).parts, 'MANAGEMENT_SOURCE_PATH')
    for part in (path, *list(path.parents)[:len(Path(name).parts) - 1]):
        need(not part.is_symlink(), 'MANAGEMENT_SOURCE_LINK')
    need(path.is_file(), 'MANAGEMENT_SOURCE_MISSING')
    return path.read_bytes()


def build_plan(old, root=ROOT, package=None):
    """Compare a verified old installation with the actual final shipped payload."""
    need(type(old) is dict and set(old) == {'schemaVersion', 'files'} and
         type(old['schemaVersion']) is int and old['schemaVersion'] == 1 and
         type(old['files']) is dict and bool(old['files']), 'INSTALL_MANIFEST')
    package = generate_package(root) if package is None else verify_package(root, package)
    lock = old['files'].get('/opt/bridge/upstream.lock.json')
    need(lock and lock['sha256'] == package['upstreamLockSha256'], 'MANAGEMENT_UPSTREAM_CHANGE')
    # An installed package must have the core entrypoints; a sparse/foreign
    # manifest cannot silently be treated as a supported installation.
    for name in ('bridge_m2/control.py', 'bridge_m4/authority.py', 'bridge_m4/web.py'):
        need('/opt/bridge/' + name in old['files'], 'UNSUPPORTED_INSTALLATION')
    desired = package['files']
    changes = []
    previous = {}
    for target, pin in sorted(old['files'].items()):
        need(type(target) is str and Path(target).is_absolute() and '..' not in Path(target).parts,
             'INSTALL_PATH')
        need(type(pin) is dict and set(pin) == {'sha256', 'mode'} and
             type(pin['mode']) is int, 'INSTALL_MANIFEST')
        if target.startswith('/opt/bridge/') and eligible(target[len('/opt/bridge/'):]):
            previous[target[len('/opt/bridge/'):]] = pin
    for name in sorted(set(previous) | set(desired)):
        before = previous.get(name)
        entry = desired.get(name)
        after = None if entry is None else {k: entry[k] for k in ('sha256', 'mode')}
        if before != after:
            changes.append({'target': '/opt/bridge/' + name, 'source': name,
                            'before': before, 'after': after,
                            'operation': 'delete' if after is None else 'add' if before is None else 'modify'})
    return {'schemaVersion': 1, 'kind': 'MANAGEMENT_SOURCE_UPDATE',
            'installedManifestSha256': sha(canonical(old)),
            'packageSha256': sha(canonical(package)), 'dependencies': package['dependencies'],
            'changes': changes, 'preserveOfficialBinaries': True,
            'preserveDatabases': True, 'preserveDnsOwnership': True, 'restartDae': False}


def deployment():
    """Accept declared layouts, or prove an existing native DNS installation.

    No old service is started and no legacy release.json is synthesized.
    """
    from bridge_m4.deployment_profile import load, validate, DNS_UNITS, selected_policy_dns, POLICY_UNITS, show, retired_policy_dns
    from bridge_m4.dns_sync_runtime import read_status
    from bridge_m4.native_dns_health import address
    profile = load()
    if profile is not None and profile['dnsOwnership'] != 'native-dae':
        return profile
    status, expected = read_status()
    need(status.get('state') == 'running' and status.get('configSha256') == expected,
         'UPGRADE_DATAPLANE_IDENTITY')
    address(status)  # Both protocols and actual PID ownership; no port-only guess.
    inferred = validate({'schemaVersion':1,'layoutVersion':1,
                         'dnsOwnership':'native-dae','policyDnsUnits':[]})
    selected_policy_dns(inferred, {n:show(n) for n in POLICY_UNITS})
    for name in DNS_UNITS:
        value = control('show', name, '--property=LoadState,ActiveState,MainPID,ControlPID,UnitFileState').stdout
        fields = dict(line.split('=',1) for line in value.splitlines() if '=' in line)
        if name.endswith('.timer'):
            # Timer units have no MainPID/ControlPID properties. Inactive +
            # disabled/masked/static is their actual retirement identity.
            retired = (fields.get('ActiveState') == 'inactive' and
                ((fields.get('LoadState') == 'not-found' and fields.get('UnitFileState') == '') or
                 (fields.get('LoadState') in {'loaded','masked'} and
                  fields.get('UnitFileState') in {'disabled','masked','static'})))
        else:
            retired = retired_policy_dns(fields)
        need(retired, 'UPGRADE_RETIRED_DNS_ACTIVE')
    return inferred


def validate_extensions(root):
    # Candidate contracts must be able to read sealed existing records before
    # stopping a service. Run the existing store reader as its actual owner.
    code = ('import sys;sys.path[:0]=' + repr([str(root), '/opt/bridge/vendor']) + ';'
            'from bridge_m4.store import ExtensionStore;'
            '_,value=ExtensionStore("/var/lib/bridge-m4-client/extensions").load();'
            'print(value["extensions"].get("schemaVersion",1))')
    result = subprocess.run(['/usr/sbin/runuser','-u','independent-bridge','--',
        '/usr/bin/python3','-I','-c',code],capture_output=True,text=True,timeout=30)
    need(result.returncode == 0 and result.stdout.strip() in {'1','2'},
         'UNSUPPORTED_EXTENSION_STATE')


def runtime_plan(old, root=ROOT):
    result = build_plan(old, root)
    result['deploymentProfile'] = deployment()
    return result


def control(*args):
    return subprocess.run(['/usr/bin/systemctl', *args], check=True,
                          capture_output=True, text=True, timeout=90)


def unit(name):
    result = control('show', name, '--property=LoadState,ActiveState,MainPID,ControlPID,InvocationID,NRestarts')
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


class RecoveryFailure(RuntimeError):
    """Only bounded, value-free recovery diagnostics may leave this module."""
    def __init__(self, code, report):
        super().__init__(code)
        self.report = report


def _failure(stage, exc, name=None):
    value = {'stage': stage, 'errorType': type(exc).__name__}
    if name is not None:
        value['unit'] = name
    return value


def _restore_states(before):
    # An individual start failure cannot prevent other original services or
    # triggers from receiving their restoration attempt. Nothing is enabled.
    errors = []
    active = [name for name in (*MANAGEMENT, *TIMERS)
              if before.get(name, {}).get('ActiveState') == 'active']
    for name in active:
        try:
            control('start', name)
        except Exception as exc:
            errors.append(_failure('start', exc, name))
    for name in active:
        try:
            need(unit(name).get('ActiveState') == 'active', 'MANAGEMENT_RESTORE_STATE')
        except Exception as exc:
            errors.append(_failure('verify-start', exc, name))
    if errors:
        raise RecoveryFailure('MANAGEMENT_RESTORE_INCOMPLETE', {'errors': errors})


def _quiesce_for_restore(before):
    # Timers may already have been resumed when a post-write check failed.
    # Stop each trigger and process independently; a command error is not proof
    # of a live process, but only a fresh observation may permit file restoration.
    names = tuple(n for n in TIMERS if n in before) + MANAGEMENT
    command_errors, unsafe = [], []
    for name in names:
        try:
            control('stop', name)
        except Exception as exc:
            command_errors.append(_failure('stop', exc, name))
    for name in names:
        try:
            observed = unit(name)
            need(observed.get('ActiveState') in {'inactive', 'failed'},
                 'MANAGEMENT_STOP_NOT_CONFIRMED')
            if name.endswith('.service'):
                need(observed.get('MainPID') == '0' and observed.get('ControlPID') == '0',
                     'MANAGEMENT_PROCESS_NOT_RELEASED')
            else:
                need(observed.get('ActiveState') == 'inactive', 'MANAGEMENT_TRIGGER_NOT_RELEASED')
        except Exception as exc:
            unsafe.append(_failure('verify-stop', exc, name))
    return not unsafe, command_errors, unsafe


def _recover_failed_apply(before_units, before_dae, tx, *, begun, stopped, checks=()):
    """Recover independent stages, without restarting mixed/unknown file bytes."""
    result = {'filesRestored': not begun, 'serviceRestoreAttempted': False,
              'errors': [], 'commandWarnings': [], 'checks': []}
    if begun:
        safe, warnings, errors = _quiesce_for_restore(before_units)
        result['commandWarnings'].extend(warnings)
        result['errors'].extend(errors)
        if safe:
            try:
                tx.restore()
                result['filesRestored'] = True
            except Exception as exc:
                result['errors'].append(_failure('restore-files', exc))
        # If processes really remain live, preserve the journal for operator
        # recovery. Blindly restoring files under them is not a safe rollback.
    if stopped and result['filesRestored']:
        result['serviceRestoreAttempted'] = True
        try:
            _restore_states(before_units)
        except RecoveryFailure as exc:
            result['errors'].extend(exc.report['errors'])
        except Exception as exc:
            result['errors'].append(_failure('restore-services', exc))
    try:
        _same_dataplane(before_dae)
        result['checks'].append({'name': 'dataplane-unchanged', 'passed': True})
    except Exception as exc:
        result['errors'].append(_failure('verify-dataplane', exc))
        result['checks'].append({'name': 'dataplane-unchanged', 'passed': False})
    if result['filesRestored'] and (not stopped or result['serviceRestoreAttempted']):
        for name, verify in checks:
            try:
                verify()
                result['checks'].append({'name': name, 'passed': True})
            except Exception as exc:
                result['errors'].append(_failure(name, exc))
                result['checks'].append({'name': name, 'passed': False})
    result['complete'] = result['filesRestored'] and not result['errors']
    return result


def _same_dataplane(before):
    after = unit('dae.service')
    need(all(before.get(k) == after.get(k) for k in
             ('ActiveState', 'MainPID', 'InvocationID', 'NRestarts')), 'DAE_PROCESS_CHANGED')


def upgrade_guard():
    from bridge_m4.maintenance_state import primary_guard, install_guard
    primary_guard()
    install_guard()
    from bridge_m4.advisory import read_json
    transaction = read_json(Path('/var/lib/daed-independent-bridge/transaction.json'), owner=0)
    need(transaction.get('phase') in {'HEALTHY','ROLLED_BACK','STOPPED'}, 'UPGRADE_TRANSACTION_ACTIVE')
    from bridge_m4.management_health import _paused
    need(not _paused(), 'UPGRADE_MAINTENANCE_PAUSED')

def apply_plan(reviewed, expected_sha, *, root=ROOT):
    need(os.geteuid() == 0 and Path('/run/systemd/system').is_dir(), 'SYSTEMD_ROOT_REQUIRED')
    need(sha(canonical(reviewed)) == expected_sha, 'REVIEWED_PLAN_HASH')
    from scripts.release_geodata_update import exclusive as runtime_locks
    from scripts import m4_install_transaction as tx
    from bridge_m4.authority import manifest, policy
    from scripts.release_replace import database_snapshot, source_identity, verify_management
    with runtime_locks(), tx.exclusive():
        old = manifest(verify_all_assets=True)
        upgrade_guard()
        policy()  # Still verify the selected assets and live helper authority.
        from scripts.management_payload import dependencies
        dependencies()
        validate_extensions(root)
        actual = runtime_plan(old, root)
        need(actual == reviewed, 'REVIEWED_PLAN_STALE')
        if not actual['changes']:
            return {'result': 'NO_CHANGE', 'applied': False, 'changedFiles': 0}
        for row in actual['changes']:
            target = Path(row['target'])
            need(not target.is_symlink(), 'INSTALL_LINK')
            need(row['before'] is not None or not target.exists(), 'UNMANAGED_INSTALL_FILE')
        new_directories = set()
        for row in actual['changes']:
            parent = Path(row['target']).parent
            while not parent.exists():
                need(str(parent).startswith('/opt/bridge/'), 'MANAGEMENT_NEW_DIRECTORY_SCOPE')
                new_directories.add(str(parent));parent=parent.parent
            need(not parent.is_symlink(), 'MANAGEMENT_DIRECTORY_LINK')
        verify_management()
        from bridge_m4.deployment_profile import lifecycle_units, load as load_layout
        selected_timers = lifecycle_units(TIMERS, actual['deploymentProfile'])
        before_units = {name: unit(name) for name in (*MANAGEMENT, *selected_timers)}
        need(all(u.get('ActiveState') in {'active','inactive'} for u in before_units.values()),
             'MANAGEMENT_TRANSITION_IN_PROGRESS')
        before_dae = unit('dae.service')
        need(before_dae.get('ActiveState') == 'active' and int(before_dae.get('MainPID', '0')) > 0,
             'DAE_NOT_RUNNING')
        with tempfile.TemporaryDirectory(prefix='management-review-', dir=str(tx.ROOT)) as directory:
            before_db = database_snapshot(Path(directory))
            before_source = source_identity()
            # Materialize and verify every input before stopping a service.
            staged = {}
            for row in actual['changes']:
                body = None if row['after'] is None else _source(root, row['source'])
                need(body is None or sha(body) == row['after']['sha256'], 'SOURCE_CHANGED')
                staged[row['target']] = body
            begun = False
            stopped = False
            try:
                stopped = True
                active_timers = [name for name in selected_timers if before_units[name]['ActiveState'] == 'active']
                if active_timers: control('stop', *active_timers)
                active_management = [name for name in MANAGEMENT if before_units[name]['ActiveState'] == 'active']
                if active_management: control('stop', *active_management)
                _same_dataplane(before_dae)
                # No program file can change until all owned management processes stop.
                for name in MANAGEMENT:
                    u = unit(name)
                    need(u.get('ActiveState') in {'inactive', 'failed'} and u.get('MainPID', '0') == '0'
                         and u.get('ControlPID', '0') == '0',
                         'MANAGEMENT_STOP_NOT_CONFIRMED')
                layout_path = LAYOUT
                tx.begin(set(staged) | {str(INSTALL), str(layout_path)})
                begun = True
                journal = tx.load()
                backup = tx.ROOT / journal['generation']
                for item in journal['files']:
                    if item['backup'] is not None:
                        need(sha((backup / item['backup']).read_bytes()) == item['sha256'], 'BACKUP_INTEGRITY')
                snapshots = list(Path(directory).glob('database-check-*.sqlite'))
                need(len(snapshots) == 1 and sha(snapshots[0].read_bytes()) == before_db, 'DATABASE_BACKUP_INTEGRITY')
                tx.write(backup / 'database.sqlite', snapshots[0].read_bytes(), 0o600)
                journal['createdDirectories'] = sorted(new_directories, key=lambda x:len(Path(x).parts))
                tx.journal(journal)  # Durable before the first mkdir, for crash recovery.
                for name in journal['createdDirectories']:
                    Path(name).mkdir(mode=0o755)
                desired = dict(old['files'])
                for row in actual['changes']:
                    if row['after'] is None:
                        Path(row['target']).unlink()
                        tx.sync(Path(row['target']).parent)
                        desired.pop(row['target'])
                    else:
                        tx.write(Path(row['target']), staged[row['target']], row['after']['mode'])
                        desired[row['target']] = row['after']
                tx.write(INSTALL, canonical({'schemaVersion': 1, 'files': desired}), 0o644)
                if not layout_path.exists():
                    tx.write(layout_path, canonical(actual['deploymentProfile']), 0o644)
                _restore_states(before_units)
                verify_management()
                _same_dataplane(before_dae)
                need(database_snapshot(Path(directory)) == before_db, 'DATABASE_CHANGED')
                need(source_identity() == before_source, 'SOURCE_CHANGED')
                # Re-read the manifest from the newly installed helper implementation.
                from scripts.release_health import check
                check()
                tx.commit()
                return {'result': 'APPLIED', 'applied': True, 'changedFiles': len(staged),
                        'daePid': int(before_dae['MainPID'])}
            except BaseException as original:
                recovery = _recover_failed_apply(before_units, before_dae, tx,
                    begun=begun, stopped=stopped, checks=(
                        ('management-health', verify_management),
                        ('database-unchanged', lambda: need(
                            database_snapshot(Path(directory)) == before_db, 'ROLLBACK_DATABASE_CHANGED')),
                        ('source-unchanged', lambda: need(source_identity() == before_source,
                                                        'ROLLBACK_SOURCE_CHANGED')),
                        ('manifest-restored', lambda: need(manifest() == old, 'ROLLBACK_MANIFEST_CHANGED'))))
                recovery['originalErrorType'] = type(original).__name__
                if not recovery['complete']:
                    raise RecoveryFailure('MANAGEMENT_ROLLBACK_INCOMPLETE', recovery) from original
                print(json.dumps({'result': 'ROLLED_BACK', 'recovery': recovery}, sort_keys=True), flush=True)
                raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--plan', action='store_true')
    group.add_argument('--apply-plan', type=Path)
    group.add_argument('--legacy-v031', action='store_true')
    parser.add_argument('--expected-plan-sha256')
    args = parser.parse_args(argv)
    sys.path.append('/opt/bridge/vendor')
    if args.legacy_v031:
        need(not args.expected_plan_sha256, 'ARGUMENTS_REJECTED')
        return main(['--plan'])
    if args.apply_plan:
        need(bool(args.expected_plan_sha256), 'REVIEWED_PLAN_HASH_REQUIRED')
        from bridge_m4.advisory import read_json
        reviewed = read_json(args.apply_plan, owner=os.geteuid())
        result = apply_plan(reviewed, args.expected_plan_sha256)
    else:
        need(not args.expected_plan_sha256, 'ARGUMENTS_REJECTED')
        from bridge_m4.authority import manifest
        plan = runtime_plan(manifest(verify_all_assets=True))
        result = {'result': 'PLAN_ONLY', 'applied': False, 'planSha256': sha(canonical(plan)), 'plan': plan, 'package': generate_package(ROOT)}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {'result': 'NOT_COMPLETED', 'error': str(exc) if isinstance(exc, RuntimeError)
                  else type(exc).__name__}
        if isinstance(exc, RecoveryFailure):
            result['recovery'] = exc.report
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
