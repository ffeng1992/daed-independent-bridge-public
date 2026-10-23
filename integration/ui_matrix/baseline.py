"""Read-only certification of an ALREADY prepared disposable matrix VM."""
import json
import os
import subprocess
from pathlib import Path
from . import evidence_scope as s
from . import completion as c


def main():
    binding, folder = s.current()
    s.require(os.environ.get('BRIDGE_DISPOSABLE_MATRIX') == binding['bootId'], 'DISPOSABLE_VM_REQUIRED')
    from scripts.m4_install import verify_installed
    from bridge_m4.dns_sync_runtime import read_status
    from .continue_global import Matrix
    for tool in ('node','ip','dig'):
        subprocess.run([tool,'--version' if tool == 'node' else '-V' if tool == 'ip' else '-v'],
            check=True,capture_output=True,timeout=5)
    manifest = json.loads(Path('/etc/daed-independent-bridge/install.json').read_text())
    verify_installed(manifest)
    health = subprocess.run(['sh', 'health-check.sh'], cwd=s.SOURCE,
                            capture_output=True, timeout=180, check=False)
    c.atomic_once(folder,'baseline-health.json', {'returncode':health.returncode,
        'stdoutSha256':s.sha(health.stdout),'stderrSha256':s.sha(health.stderr)})
    s.require(health.returncode == 0, 'BASELINE_HEALTH_FAILED')
    matrix = Matrix()
    status, expected = read_status()
    s.require(status['state'] == 'running' and status['identityVerified'] is True and
              status['activeBundle'] and status['configSha256'] == expected, 'BASELINE_DAE_IDENTITY')
    core = subprocess.run(['systemctl','show','dae.service','--property=MainPID,InvocationID,ActiveState,SubState'],
        capture_output=True,text=True,check=True).stdout
    fields = dict(x.split('=',1) for x in core.splitlines() if '=' in x)
    s.require(fields['ActiveState'] == 'active' and fields['SubState'] == 'running' and
              int(fields['MainPID']) > 0 and fields['InvocationID'], 'BASELINE_SYSTEMD_IDENTITY')
    processes = subprocess.run(['pgrep','-x','dae'],capture_output=True,text=True,check=False)
    s.require(processes.returncode == 0 and processes.stdout.split() == [fields['MainPID']], 'BASELINE_MULTIPLE_DAE')
    topology = subprocess.run(['ip','-j','address','show'],capture_output=True,text=True,check=True)
    links = json.loads(topology.stdout)
    s.require({'lan0','client0','wan0','wanpeer'} <= {x['ifname'] for x in links}, 'BASELINE_TOPOLOGY_MISSING')
    # A selected profile and read-back of modified=false are independently
    # required, not inferred from systemd process existence.
    for collection in ('configs','dnss','routings'):
        s.require(sum(x['selected'] is True for x in matrix.source['metadata'][collection]) == 1,
                  'BASELINE_SELECTION')
    s.require(matrix.api('{general{dae{running modified}}}')['general']['dae'] ==
              {'running':True,'modified':False}, 'BASELINE_SOURCE_NOT_APPLIED')
    from bridge_m2.control import BASE
    transaction = BASE/'transaction.json'
    if transaction.exists():
        t = json.loads(transaction.read_text())
        s.require(t.get('phase') in ('HEALTHY','ROLLED_BACK','STOPPED'), 'BASELINE_PENDING_TRANSACTION')
    s.require(not (BASE/'rollback-required').exists(), 'BASELINE_ROLLBACK_NEEDED')
    c.atomic_once(folder,'baseline-identity.json', {'scope':binding,'systemd':fields,
        'status':status,'expected':expected,'sourceSha256':s.sha(c.encoded(matrix.source)),
        'manifestSha256':s.sha(c.encoded(manifest)), 'topology':links})
    cases = ['health','official-identity','unique-dae','source-and-config','fixture-topology','no-transaction']
    c.atomic_once(folder,'baseline-observations.json', [
        {'id':k,'result':'RUNTIME_PASS','restored':True} for k in cases])


if __name__ == '__main__':
    main()
