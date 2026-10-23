"""Native-DAE DNS lifecycle; no policy DNS service or configuration is adopted.

Called by the release CLI while holding bridge-release.lock. Service operations
belong only in an explicitly authorized systemd installation or disposable VM.
This module does not change official daed configuration or official binaries.
The ordinary installer still verifies official payload identities before writing.
"""
import json
import contextlib
import fcntl
import uuid
import os
import grp
import pwd
from pathlib import Path
import stat
import subprocess
import time

from bridge_m4.deployment_profile import (validate, load, DNS_UNITS,
                                           POLICY_UNITS, retired_policy_dns)

CFG = Path('/etc/daed-independent-bridge')
MANIFEST = CFG / 'install.json'
NATIVE = {'schemaVersion': 1, 'layoutVersion': 1,
          'dnsOwnership': 'native-dae', 'policyDnsUnits': []}
CORE = ('daed-api.service', 'bridge-helper.socket', 'bridge-attestor.service',
        'independent-bridge.service', 'dae.service', 'bridge-graphql.service', 'daed-web.service')
TIMERS = ('bridge-geodata-update.timer', 'bridge-management-recovery.timer')
PERIODIC = ('bridge-geodata-update.service', 'bridge-management-recovery.service')
ONESHOTS = (*PERIODIC, 'bridge-helper.service')
# The helper is socket-activated, not a periodic oneshot. Close it before its service.
TRIGGERS = (*TIMERS, 'bridge-helper.socket')
DRAIN_TIMEOUT = 90.0
OWNED = (*CORE, *TIMERS, *ONESHOTS)
# Refuse a still-active/boot-enabled old consumer; never stop or adopt it.
RETIRED = tuple(sorted(DNS_UNITS | {'dae-policy-dns.service'}))
SETUP_FILES = ('release.json', 'health.json', 'web.json', 'tls.crt', 'tls.key',
               'layout.json', 'setup-pending', 'bridge-login.token', 'backend.token')


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def ctl(*args, timeout=90):
    return subprocess.run(['/usr/bin/systemctl', *args], capture_output=True,
                          text=True, timeout=timeout, check=True)


def observe(name, *, allow_transition=False, deadline=None):
    """Read state, not health. Transitional reads are only for bounded draining/stopping.

    The default is deliberately still strict, including for retired consumers.
    No caller may use allow_transition to certify a healthy or restored service.
    """
    need(name in OWNED or name in RETIRED, 'NATIVE_UNIT_NOT_OWNED')
    need(not allow_transition or name in OWNED, 'NATIVE_UNIT_NOT_OWNED')
    properties = 'LoadState,ActiveState,MainPID,ControlPID,UnitFileState'
    if allow_transition and name in PERIODIC:
        properties += ',Type,RemainAfterExit'
    if deadline is None:
        raw = ctl('show', name, '--all', '--property=' + properties).stdout
    else:
        remaining = deadline - time.monotonic()
        need(remaining > 0, 'NATIVE_PERIODIC_DRAIN_TIMEOUT')
        raw = ctl('show', name, '--all', '--property=' + properties, timeout=min(90, remaining)).stdout
        need(time.monotonic() < deadline, 'NATIVE_PERIODIC_DRAIN_TIMEOUT')
    value = dict(row.split('=', 1) for row in raw.splitlines() if '=' in row)
    need(value.get('LoadState') in {'loaded', 'not-found', 'masked'}, 'NATIVE_UNIT_STATE_UNKNOWN')
    allowed = {'active', 'inactive', 'failed'}
    if allow_transition:
        allowed |= {'activating', 'deactivating', 'reloading'}
    need(value.get('ActiveState') in allowed, 'NATIVE_UNIT_TRANSITION')
    for key in ('MainPID', 'ControlPID'):
        if name.endswith('.service'):
            need(str(value.get(key, '')).isascii() and str(value.get(key, '')).isdigit(),
                 'NATIVE_UNIT_PID_UNKNOWN')
    if allow_transition and name in PERIODIC and value['LoadState'] == 'loaded':
        need(value.get('Type') == 'oneshot' and value.get('RemainAfterExit') == 'no',
             'NATIVE_PERIODIC_UNIT_IDENTITY')
    return value


def quiet(name, value):
    return (value.get('ActiveState') in {'inactive', 'failed'} and
            (not name.endswith('.service') or
             value.get('MainPID') == value.get('ControlPID') == '0'))


def verify_retired():
    for name in RETIRED:
        value = observe(name)
        need(quiet(name, value), 'NATIVE_UNDECLARED_DNS_CONSUMER')
        if value['LoadState'] != 'not-found':
            need(value.get('UnitFileState') in {'disabled', 'masked', 'static'},
                 'NATIVE_RETIRED_DNS_BOOT_ENABLED')
        if name in POLICY_UNITS:
            need(retired_policy_dns(value), 'NATIVE_UNDECLARED_DNS_CONSUMER')


def verify_configuration():
    # release.json and old lan/policy-dns.conf are NOT native upgrade prerequisites.
    need(load(CFG/'layout.json') == NATIVE, 'NATIVE_LAYOUT_REQUIRED')
    for name in ('web.json', 'tls.crt', 'tls.key', 'health.json'):
        path = CFG / name
        st = path.lstat()
        need(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and st.st_nlink == 1
             and not st.st_mode & 0o022, 'NATIVE_CONFIGURATION_AUTHORITY')
    if not (CFG/'setup-pending').exists():
        for path in (CFG/'attestor.token', Path('/var/lib/bridge-m4-client/extensions/current')):
            need(path.is_file() and not path.is_symlink(), 'NATIVE_INITIAL_CONFIGURATION_REQUIRED')
        need(Path('/var/lib/daed-independent-bridge/current').is_symlink(),
             'NATIVE_INITIAL_BUNDLE_REQUIRED')


def stop_triggers(names):
    """Stop every trigger, then prove all are quiet before touching consumers.

    A command error is retained even if fresh state proves the stop completed.
    An unconfirmed trigger stop aborts; stopping unrelated services cannot help.
    """
    need(set(names) <= set(TRIGGERS), 'NATIVE_TRIGGER_NOT_OWNED')
    warnings = []
    for name in names:
        try:
            value = observe(name, allow_transition=True)
            if value['LoadState'] != 'not-found':
                ctl('stop', name)
        except Exception as exc:
            warnings.append({'unit': name, 'stage': 'trigger-stop',
                             'exception': type(exc).__name__})
    for name in names:
        need(quiet(name, observe(name)), 'NATIVE_TRIGGER_STOP_NOT_CONFIRMED')
    return warnings


def drain_periodic(*, timeout=DRAIN_TIMEOUT):
    """Wait for in-flight jobs to finish naturally after their timers are stopped.

    Release/install locks and the existing-install apply lock are held. One monotonic
    deadline, no retry of the lifecycle operation and no signal/kill escalation.
    """
    need(type(timeout) in (int, float) and 0 < timeout <= DRAIN_TIMEOUT,
         'NATIVE_DRAIN_TIMEOUT_RANGE')
    deadline = time.monotonic() + timeout
    while True:
        for name in TIMERS:
            need(quiet(name, observe(name, deadline=deadline)), 'NATIVE_TRIGGER_REACTIVATED')
        states = {name: observe(name, allow_transition=True, deadline=deadline) for name in PERIODIC}
        if all(quiet(name, value) for name, value in states.items()):
            # A second complete observation rejects reactivation during collection.
            again = {name: observe(name, allow_transition=True, deadline=deadline) for name in PERIODIC}
            if all(quiet(name, value) for name, value in again.items()):
                for name in TIMERS:
                    need(quiet(name, observe(name, deadline=deadline)), 'NATIVE_TRIGGER_REACTIVATED')
                need(time.monotonic() < deadline, 'NATIVE_PERIODIC_DRAIN_TIMEOUT')
                return again
        remaining = deadline - time.monotonic()
        need(remaining > 0, 'NATIVE_PERIODIC_DRAIN_TIMEOUT')
        time.sleep(min(0.1, remaining))


def restore_timers(before):
    """Undo trigger preflight only. No enable changes, worker replay or core control."""
    need(type(before) is dict and set(before) == set(TIMERS), 'NATIVE_TIMER_SNAPSHOT')
    errors = []
    for name in TIMERS:
        old = before[name]
        try:
            current = observe(name)
            need(current.get('LoadState') == old.get('LoadState') and
                 current.get('UnitFileState') == old.get('UnitFileState'),
                 'NATIVE_TIMER_CONFIGURATION_CHANGED')
            if old['LoadState'] != 'not-found':
                ctl('start' if old['ActiveState'] == 'active' else 'stop', name)
        except Exception as exc:
            errors.append({'unit': name, 'stage': 'trigger-restore',
                           'exception': type(exc).__name__})
    for name in TIMERS:
        try:
            current, old = observe(name), before[name]
            need((current['ActiveState'] == 'active') == (old['ActiveState'] == 'active') and
                 current.get('LoadState') == old.get('LoadState') and
                 current.get('UnitFileState') == old.get('UnitFileState'),
                 'NATIVE_TIMER_RESTORE_MISMATCH')
        except Exception as exc:
            errors.append({'unit': name, 'stage': 'trigger-readback',
                           'exception': type(exc).__name__})
    return errors


def recover_trigger_preflight(attempt, tx, install):
    """Crash-safe recovery before any consumer stop or installer write."""
    result = {'complete': False, 'scope': 'triggers-only',
              'filesTouched': False, 'coreServicesTouched': False, 'errors': []}
    try:
        journal = tx.load()
        need((journal.get('generation') if journal else None) == attempt['previousGeneration'] and
             (not journal or journal.get('phase') in {'COMMITTED', 'RESTORED'}),
             'NATIVE_PREFLIGHT_TRANSACTION_CHANGED')
        record = attempt['manifestBefore']
        if record is None:
            need(not MANIFEST.exists(), 'NATIVE_UNEXPECTED_MANIFEST')
        else:
            need(json.loads(MANIFEST.read_text()) == record, 'NATIVE_MANIFEST_RESTORE_MISMATCH')
            install.verify_installed(record)
        result['errors'] = restore_timers(attempt['beforeTimers'])
        result['complete'] = not result['errors']
    except Exception as exc:
        result['errors'].append({'stage': 'trigger-recovery', 'exception': type(exc).__name__})
    return result


def stop_owned():
    # Never let a timer/socket reactivate a service during file replacement.
    failures = stop_triggers(TRIGGERS)
    names = (*ONESHOTS, *(n for n in reversed(CORE) if n not in TRIGGERS))
    for name in names:
        try:
            value = observe(name, allow_transition=True)
            if value['LoadState'] != 'not-found':
                ctl('stop', name)
        except Exception as exc:
            failures.append({'unit': name, 'exception': type(exc).__name__})
    live = []
    for name in OWNED:
        try:
            value = observe(name)
            if not quiet(name, value):
                live.append(name)
            elif value['ActiveState'] == 'failed':
                ctl('reset-failed', name)
        except Exception:
            live.append(name)
    need(not live, 'NATIVE_STOP_NOT_CONFIRMED')
    return failures


def restore_units(before):
    """Restore durable service intent; re-enable schedules only after readback.

    The preflight drained periodic jobs. Do not replay them, nor require them
    to remain inactive after restoring timers (oneshots may then run normally).
    Legacy journals with active periodic jobs are rejected, not reinterpreted.
    """
    errors = []
    for name in PERIODIC:
        if not quiet(name, before[name]):
            return [{'unit': name, 'stage': 'periodic-snapshot',
                     'exception': 'NATIVE_PERIODIC_REPLAY_REFUSED'}]
    def restore_group(names):
        for name in names:
            value = before[name]
            enabled = value.get('UnitFileState')
            try:
                if enabled in {'enabled', 'enabled-runtime'}:
                    ctl('enable', *(['--runtime'] if enabled == 'enabled-runtime' else []), name)
                elif value.get('LoadState') != 'not-found' and enabled == 'disabled':
                    ctl('disable', name)
            except Exception as exc:
                errors.append({'unit': name, 'stage': 'enable-state', 'exception': type(exc).__name__})
            try:
                if value['ActiveState'] == 'active':
                    ctl('start', name)
            except Exception as exc:
                errors.append({'unit': name, 'stage': 'start', 'exception': type(exc).__name__})
        for name in names:
            old = before[name]
            try:
                current = observe(name)
                need((current['ActiveState'] == 'active') == (old['ActiveState'] == 'active'),
                     'NATIVE_RESTORE_ACTIVE_MISMATCH')
                if old.get('UnitFileState') in {'enabled', 'enabled-runtime', 'disabled', 'static'}:
                    need(current.get('UnitFileState') == old['UnitFileState'], 'NATIVE_RESTORE_ENABLE_MISMATCH')
                if name in PERIODIC:
                    need(quiet(name, current), 'NATIVE_PERIODIC_REACTIVATED')
            except Exception as exc:
                errors.append({'unit': name, 'stage': 'readback', 'exception': type(exc).__name__})
    # Fixed daemons and helper are restored/read back before timer activation.
    restore_group((*CORE, *ONESHOTS))
    # Files were already completely restored by recover(). Attempt every timer
    # as well, retaining all earlier failures rather than short-circuiting recovery.
    restore_group(TIMERS)
    return errors


def start_native(*, setup=False):
    from scripts.release_lifecycle import wait_for_management, wait_for_dataplane
    units = tuple(name for name in CORE if not setup or name not in {'dae.service', 'bridge-attestor.service'})
    ctl('daemon-reload')
    ctl('enable', *units)
    ctl('start', *units)
    wait_for_management()
    if not setup:
        wait_for_dataplane()
        ctl('enable', '--now', *TIMERS)
    else:
        ctl('enable', '--now', 'bridge-management-recovery.timer')
    # Never enable independent-dns-sync or independent-policy-sync.


def recover(before, original_generation, tx, *, manifest_before, install, attempt_id=None, directories_before=None):
    """Do not start any service if files cannot be proved completely restored."""
    result = {'complete': False, 'filesRestored': False, 'errors': []}
    try:
        result['stopWarnings'] = stop_owned()
        # Undo boot links while candidate unit files still exist.
        for name, value in before.items():
            if value.get('UnitFileState') not in {'enabled', 'enabled-runtime'}:
                try:
                    if observe(name)['LoadState'] != 'not-found': ctl('disable', name)
                except Exception as exc:
                    result['errors'].append({'unit': name, 'stage': 'disable', 'exception': type(exc).__name__})
        journal = tx.load()
        if journal and journal.get('generation') != original_generation:
            need(journal.get('context') == {'kind':'native-lifecycle','attemptId':attempt_id},
                 'NATIVE_INSTALL_TRANSACTION_BINDING')
            need(journal.get('phase') in {'APPLYING', 'COMMITTED', 'RESTORING','RESTORED'}, 'NATIVE_RECOVERY_JOURNAL')
            if journal['phase'] != 'RESTORED':tx.restore()
            need(tx.load().get('phase') == 'RESTORED', 'NATIVE_FILE_RESTORE_INCOMPLETE')
        if manifest_before is not None:
            need(json.loads(MANIFEST.read_text()) == manifest_before, 'NATIVE_MANIFEST_RESTORE_MISMATCH')
            install.verify_installed(manifest_before)
        else:
            need(not MANIFEST.exists(), 'NATIVE_UNEXPECTED_MANIFEST')
        result['filesRestored'] = True
        ctl('daemon-reload')
    except Exception as exc:
        result['errors'].append({'stage': 'files', 'exception': type(exc).__name__})
        return result
    if directories_before is not None:
        try:
            result['newEmptyDirectoriesRemoved']=remove_new_empty_directories(directories_before)
        except Exception as exc:
            result['errors'].append({'stage':'directory-cleanup','exception':type(exc).__name__})
    result['errors'].extend(restore_units(before))
    if manifest_before is not None and before['dae.service']['ActiveState'] == 'active':
        try:
            from scripts.release_health import check
            from scripts.release_lifecycle import wait_for_management, wait_for_dataplane
            # Restoring Type=simple units proves process start, not readiness.
            # Reuse the normal startup's bounded, read-only identity waits;
            # the complete health gate below remains mandatory.
            wait_for_management()
            wait_for_dataplane()
            check(require_dataplane=True)
        except Exception as exc:
            # Persist only a constant-style error code, never URLs, tokens or payloads.
            import re
            detail = str(exc)
            code = detail if re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', detail) else 'UNCLASSIFIED_RECOVERY_HEALTH_ERROR'
            result['errors'].append({'stage': 'health', 'exception': type(exc).__name__, 'code': code})
    if manifest_before is None:
        remaining=[str(p) for p in (Path('/var/lib/bridge-daed/wing.db'),
                   Path('/var/lib/bridge-m4-client/extensions/current')) if p.exists() or p.is_symlink()]
        if remaining:
            result['retainedState']=remaining
            result['errors'].append({'stage':'retained-new-state','exception':'NATIVE_NEW_STATE_REQUIRES_REVIEW'})
    result['complete'] = not result['errors']
    return result


def execute(action, args):
    """install/reinstall/upgrade/uninstall retaining data, only for native layout.

    Purging persistent data is intentionally a separate unsupported native action:
    refusal occurs before service/file changes, not a partly destructive uninstall.
    Explicit daed authorization remains a separate setup action because it edits
    credentials and publishes a configuration, not an installer rollback scope.
    """
    need(action in {'install', 'upgrade', 'uninstall'}, 'NATIVE_LIFECYCLE_ACTION')
    need(not getattr(args, 'purge', False), 'NATIVE_PURGE_REQUIRES_SEPARATE_DATA_REVIEW')
    connect_requested = getattr(args, 'connect_daed', False)
    need(not connect_requested or action=='install', 'NATIVE_AUTHORIZE_INSTALL_OPTION_ONLY')
    from scripts import m4_install as install, m4_install_transaction as tx
    from bridge_m4.maintenance_state import primary_guard
    from scripts import release_setup as setup
    from scripts.release_lifecycle import ready_payload, packages, same_payload
    from scripts.release_health import check as health
    with tx.exclusive(), contextlib.ExitStack() as stack:
        pending = read_attempt(tx)
        if getattr(args, 'recover_native', False):
            need(pending is not None and pending['phase'] not in {'ACCEPTED','RESTORED'},
                 'NATIVE_NO_PENDING_RECOVERY')
            primary_guard()
            if Path('/var/lib/daed-independent-bridge/apply.lock').exists():
                stack.enter_context(apply_lock())
            if pending.get('recoveryScope') == 'triggers-only':
                outcome = recover_trigger_preflight(pending, tx, install)
            else:
                outcome = recover(pending['beforeUnits'], pending['previousGeneration'], tx,
                    manifest_before=pending['manifestBefore'], install=install,
                    attempt_id=pending['attemptId'],directories_before=pending.get('directoriesBefore'))
            save_attempt(tx,pending,'RESTORED' if outcome['complete'] else 'RECOVERY_REQUIRED',outcome)
            print(json.dumps({'nativeRecovery':outcome},sort_keys=True))
            need(outcome['complete'],'NATIVE_RECOVERY_INCOMPLETE')
            return
        need(pending is None or pending['phase'] in {'ACCEPTED','RESTORED'},
             'NATIVE_PENDING_LIFECYCLE_USE_RECOVER_NATIVE')
        prior = tx.load()
        need(not prior or prior.get('phase') in {'COMMITTED', 'RESTORED'}, 'NATIVE_PENDING_INSTALL_RECOVERY')
        primary_guard()
        verify_retired()
        record = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None
        profile = load(CFG/'layout.json')
        need(profile is None or profile == NATIVE, 'NATIVE_LAYOUT_CONVERSION_NOT_AUTHORIZED')
        need(action != 'upgrade' or record is not None, 'UPGRADE_REQUIRES_INSTALLATION')
        retained = profile == NATIVE
        need(not connect_requested or (record is not None and retained),
             'NATIVE_AUTHORIZE_SEPARATELY_AFTER_INSTALL')
        fresh = record is None and not retained
        if fresh:
            need(action == 'install', 'NATIVE_INSTALLATION_NOT_FOUND')
            need(not Path('/var/lib/bridge-daed').exists() and not CFG.exists(), 'NATIVE_EXISTING_STATE_NOT_ADOPTED')
            value = setup.settings(getattr(args, 'settings', None))
            need(Path('/sys/class/net', value['lanInterface']).exists(), 'LAN_INTERFACE_NOT_FOUND')
        else:
            verify_configuration()
        locked_apply=False
        if record is None:
            unmanaged = {name: observe(name) for name in OWNED}
            need(all(quiet(n, v) for n, v in unmanaged.items()), 'NATIVE_UNMANAGED_ACTIVE_SERVICE')
        else:
            install.verify_installed(record)
            # Native ownership must not silently migrate old self-managed DNS.
            need(not any(n.startswith('/etc/dae-dns-repair/') or
                         n in {'/etc/systemd/system/'+u for u in RETIRED}
                         for n in record['files']),
                 'NATIVE_EXTERNAL_DNS_MIGRATION_REQUIRES_PLAN')
        if action != 'uninstall':
            for account in ('independent-bridge','bridge-daed'):
                user=pwd.getpwnam(account)
                need(user.pw_uid!=0 and user.pw_shell=='/usr/sbin/nologin' and
                     grp.getgrgid(user.pw_gid).gr_name==account,'NATIVE_ACCOUNT_PREREQUISITES')
            packages(native_dns=True)
            files = ready_payload(native_dns=True)
            if record is not None:
                import hashlib
                for name in ('/opt/bridge-official/daed','/opt/bridge-official/dae','/opt/bridge-service/dae'):
                    need(name in files and record['files'].get(name,{}).get('sha256')==hashlib.sha256(files[name][0]).hexdigest(),
                         'NATIVE_OFFICIAL_COMPONENT_CHANGE_REQUIRES_MIGRATION')
            if action == 'install' and record:
                need(same_payload(files, record), 'ALREADY_INSTALLED_DIFFERENT_VERSION_USE_UPGRADE')
                if connect_requested:
                    from scripts.release_lifecycle import connect_daed
                    connect_daed()
                else:
                    health(require_dataplane=not (CFG/'setup-pending').exists())
                print(json.dumps({'alreadyInstalled': True, 'dnsOwnership': 'native-dae'}))
                return
        elif record is None:
            print(json.dumps({'uninstalled': True, 'persistentDataRetained': True}))
            return
        if record is not None or retained:
            stack.enter_context(apply_lock());locked_apply=True
        old_generation = prior.get('generation') if prior else None
        # Persist intent BEFORE stopping even a timer. A crash here is recoverable
        # by --recover-native without restarting a daemon or restoring program files.
        timers_before = {name: observe(name) for name in TIMERS}
        attempt={'schemaVersion':1,'attemptId':uuid.uuid4().hex,'phase':'QUIESCING',
                 'recoveryScope':'triggers-only','beforeTimers':timers_before,
                 'previousGeneration':old_generation,'manifestBefore':record,
                 'directoriesBefore':directory_inventory()}
        context={'kind':'native-lifecycle','attemptId':attempt['attemptId']}
        save_attempt(tx,attempt,'QUIESCING')
        before = None
        full_prepared = False
        try:
            warnings = stop_triggers(TIMERS)
            drained = drain_periodic()
            before = {name: observe(name) for name in OWNED}
            need(all(quiet(n, before[n]) for n in (*TIMERS, *PERIODIC)),
                 'NATIVE_TRIGGER_REACTIVATED')
            # Restore timer scheduling intent, not the instantaneous maintenance job.
            before.update(timers_before)
            attempt.update(recoveryScope='full',beforeUnits=before,
                           triggerStopWarnings=warnings,drainedPeriodic=drained)
            save_attempt(tx,attempt,'PREPARED')
            full_prepared = True
            save_attempt(tx,attempt,'STOPPING')
            attempt['stopWarnings'] = stop_owned()
            if action == 'uninstall':
                install.uninstall(preserve_assets=True,native_dns=True,transaction_context=context)
                need(not MANIFEST.exists(), 'NATIVE_UNINSTALL_INCOMPLETE')
                save_attempt(tx,attempt,'ACCEPTED')
                print(json.dumps({'uninstalled': True, 'persistentDataRetained': True, 'dnsOwnership': 'native-dae'}))
                return
            extra = tuple(str(CFG/name) for name in SETUP_FILES
                          if not (CFG/name).exists() and not (CFG/name).is_symlink())
            lock_path=Path('/var/lib/daed-independent-bridge/apply.lock')
            if not lock_path.exists() and not lock_path.is_symlink():extra+=(str(lock_path),)
            save_attempt(tx,attempt,'APPLYING')
            install.install(upgrade=record is not None, preserve_assets=True,
                            release_profile=True,native_dns=True,extra_paths=extra,transaction_context=context)
            if not locked_apply:
                stack.enter_context(apply_lock());locked_apply=True
            if fresh:
                setup.configure(value, native_dns=True)
                setup.write(CFG/'setup-pending', b'Official user setup and explicit bridge authorization required.\n')
            setup.bridge_credentials()
            save_attempt(tx,attempt,'STARTING')
            start_native(setup=(CFG/'setup-pending').exists())
            health(require_dataplane=not (CFG/'setup-pending').exists())
            verify_retired()
            install.verify_installed(json.loads(MANIFEST.read_text()))
            save_attempt(tx,attempt,'ACCEPTED')
            print(json.dumps({'nativeLifecycle': 'PASS', 'action': action,
                              'setupRequired': (CFG/'setup-pending').exists()}))
        except BaseException:
            if full_prepared:
                outcome = recover(before,old_generation,tx,manifest_before=record,install=install,
                                  attempt_id=attempt['attemptId'],directories_before=attempt['directoriesBefore'])
            else:
                attempt.update(recoveryScope='triggers-only')
                attempt.pop('beforeUnits', None)
                outcome = recover_trigger_preflight(attempt, tx, install)
            save_attempt(tx,attempt,'RESTORED' if outcome['complete'] else 'RECOVERY_REQUIRED',outcome)
            print(json.dumps({'nativeLifecycle': 'ROLLED_BACK' if outcome['complete'] else 'RECOVERY_REQUIRED',
                              'recovery': outcome}, sort_keys=True))
            raise



def authorize(token):
    """Explicit post-install authorization. Leaves setup pending on any failure.

    Official configuration is selected by the user, never invented or edited by
    this installer. Runtime.apply owns the actual DAE publication and rollback.
    """
    from scripts.release_setup import connect, apply_initial
    from scripts.release_health import check as health
    verify_configuration()
    verify_retired()
    connect(token)
    ctl('restart', 'bridge-attestor.service')
    apply_initial()
    start_native(setup=False)
    health(require_dataplane=True)
    verify_retired()
    (CFG/'setup-pending').unlink(missing_ok=True)
    fd = os.open(CFG, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def apply_lock():
    path=Path('/var/lib/daed-independent-bridge/apply.lock')
    fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        st=os.fstat(fd)
        need(stat.S_ISREG(st.st_mode) and st.st_uid==st.st_gid==0 and
             st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o600,'NATIVE_APPLY_LOCK_AUTHORITY')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def read_attempt(tx):
    from bridge_m4.maintenance_state import _read
    try:
        value=_read(tx.ROOT/'native-lifecycle.json')
    except FileNotFoundError:
        return None
    need(type(value) is dict and value.get('schemaVersion')==1 and
         type(value.get('attemptId')) is str and len(value['attemptId'])==32 and
         all(c in '0123456789abcdef' for c in value['attemptId']) and
         value.get('phase') in {'QUIESCING','PREPARED','STOPPING','APPLYING','STARTING',
                               'ACCEPTED','RESTORED','RECOVERY_REQUIRED'},
         'NATIVE_LIFECYCLE_JOURNAL')
    if value['phase'] not in {'ACCEPTED','RESTORED'}:
        need('previousGeneration' in value and 'manifestBefore' in value,
             'NATIVE_LIFECYCLE_JOURNAL')
        scope = value.get('recoveryScope', 'full')  # R4/R5 pending journals remain explicit recovery inputs.
        need(scope in {'full', 'triggers-only'}, 'NATIVE_LIFECYCLE_JOURNAL')
        if scope == 'triggers-only':
            need(value['phase'] in {'QUIESCING','RECOVERY_REQUIRED'} and
                 'beforeUnits' not in value and type(value.get('beforeTimers')) is dict and
                 set(value['beforeTimers']) == set(TIMERS), 'NATIVE_LIFECYCLE_JOURNAL')
            states = value['beforeTimers']
        else:
            need(value['phase'] != 'QUIESCING' and type(value.get('beforeUnits')) is dict and
                 set(value['beforeUnits']) == set(OWNED), 'NATIVE_LIFECYCLE_JOURNAL')
            states = value['beforeUnits']
        for name, unit in states.items():
            need(type(unit) is dict and unit.get('ActiveState') in {'active','inactive','failed'}
                 and unit.get('LoadState') in {'loaded','masked','not-found'} and
                 type(unit.get('UnitFileState')) is str, 'NATIVE_LIFECYCLE_JOURNAL')
    # A completed attempt's old service set is history, not a new-upgrade gate.
    return value


def save_attempt(tx,value,phase,recovery=None):
    value=dict(value,phase=phase)
    if recovery is not None:value['recovery']=recovery
    tx.write(tx.ROOT/'native-lifecycle.json',
             (json.dumps(value,sort_keys=True)+'\n').encode(),0o600)



DIRECTORY_ROOTS = ('/etc/daed-independent-bridge','/opt/bridge','/opt/bridge-official',
    '/opt/bridge-service','/opt/bridge-daed-web','/opt/bridge-daed-web-entry',
    '/var/lib/bridge-daed','/var/lib/bridge-m4-client','/var/lib/bridge-m4-attestation',
    '/var/lib/daed-independent-bridge','/run/bridge-control')


def directory_inventory():
    found=set()
    for name in DIRECTORY_ROOTS:
        root=Path(name)
        need(not root.is_symlink(),'NATIVE_DIRECTORY_ROOT_LINK')
        if not root.exists():continue
        need(root.is_dir(),'NATIVE_DIRECTORY_ROOT_TYPE')
        found.add(str(root))
        for path in root.rglob('*'):
            if not path.is_symlink() and path.is_dir():found.add(str(path))
            need(len(found)<=10000,'NATIVE_DIRECTORY_LIMIT')
    return sorted(found)


def remove_new_empty_directories(before):
    """Only remove known new empty directories; never erase user state."""
    need(type(before) is list and all(type(p) is str for p in before),'NATIVE_DIRECTORY_SNAPSHOT')
    created=set(directory_inventory())-set(before)
    removed=[]
    for name in sorted(created,key=lambda n:len(Path(n).parts),reverse=True):
        path=Path(name)
        need(not path.is_symlink(),'NATIVE_DIRECTORY_CHANGED')
        if path.exists():
            # Nonempty means something remains to review, not permission to rm -rf.
            path.rmdir()
            removed.append(name)
    return removed
