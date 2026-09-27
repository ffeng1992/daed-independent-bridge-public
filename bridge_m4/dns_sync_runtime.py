"""Candidate one-shot adapter; never install/run this on production for rehearsal.

Only status is sent to the broker. Existing dnsdist control code is reused,
but its database snapshot/reconcile functions are never called.
"""
import json
import subprocess
import sys
from .dns_sync import reconcile

STATUS_CODE = (
    'import sys;sys.path[:0]=["/opt/bridge","/opt/bridge/vendor"];'
    'import json;from bridge_m2.submit import submit;'
    'print(json.dumps(submit("status")))'
)
# submit() bounds socket I/O at 60 seconds. The parent must permit that
# existing bound plus process startup; it must not kill a valid queued read
# after four seconds on an emulated/loaded host. Expiry still targets DOWN.
STATUS_PROCESS_TIMEOUT = 65


def bridge_identity():
    result = subprocess.run(
        ['/usr/bin/systemctl', 'show', 'independent-bridge.service', '--no-pager',
         '--property=ActiveState,SubState,MainPID,InvocationID'],
        capture_output=True, timeout=5, check=True,
        env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
    fields = dict(line.split('=', 1) for line in result.stdout.decode().splitlines() if '=' in line)
    if (fields.get('ActiveState') != 'active' or fields.get('SubState') != 'running'
            or int(fields.get('MainPID', '0')) <= 0 or not fields.get('InvocationID')):
        raise RuntimeError('BRIDGE_UNAVAILABLE')
    return fields['MainPID'], fields['InvocationID']


def read_status():
    from .authority import controller, policy
    before = bridge_identity()
    result = subprocess.run(
        ['/usr/sbin/runuser', '-u', 'independent-bridge', '--',
         '/usr/bin/python3', '-I', '-c', STATUS_CODE],
        capture_output=True, timeout=STATUS_PROCESS_TIMEOUT, check=True,
        env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
    if len(result.stdout) > 65536: raise RuntimeError('STATUS_SIZE')
    status = json.loads(result.stdout)
    if type(status) is not dict: raise RuntimeError('STATUS_SCHEMA')
    identity = status.get('activeBundle')
    expected = controller(policy()).version(identity) if identity else None
    if bridge_identity() != before:
        raise RuntimeError('BRIDGE_CHANGED')
    return status, expected


class Backends:
    def __init__(self):
        # Fixed trusted installed library, not a user-supplied import directory.
        sys.path.insert(0, '/usr/local/lib/daed-dnsdist-sync')
        from daed_dnsdist_sync.core import DnsdistControl
        self.control = DnsdistControl(('/usr/bin/dnsdist', '-c'))

    def states(self):
        servers = self.control.servers()
        if not {'DAE', 'DIRECT'} <= set(servers): raise RuntimeError('DNS_BACKEND_IDENTITY')
        return {name: servers[name].state for name in ('DAE', 'DIRECT')}

    def set_state(self, name, state):
        if name not in {'DAE', 'DIRECT'} or state not in {'UP', 'DOWN'}:
            raise RuntimeError('DNS_ACTION_REJECTED')
        servers = self.control.servers()
        self.control.set_state(servers[name], state)


def main():
    if len(sys.argv) != 1:
        print('{"error":"ARGUMENTS_REJECTED"}'); return 1
    try:
        result = reconcile(read_status, Backends())
        print(json.dumps(result, sort_keys=True))
        return 0 if result['consistent'] else 1
    except Exception:
        # Legacy control exceptions can contain console configuration/output.
        print('{"consistent":false,"error":"DNS_SYNC_FAILED"}')
        return 1


if __name__ == '__main__': raise SystemExit(main())
