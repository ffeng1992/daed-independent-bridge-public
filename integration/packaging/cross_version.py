"""Real two-tree lifecycle harness, ONLY in a disposable Debian guest.

This is not executed by importing it. The controller must provide two distinct
reviewed trees and an isolation marker. Same-tree testing is explicitly refused.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def need(value, code):
    if not value:
        raise RuntimeError(code)


def tree_identity(root):
    root = Path(root)
    files = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if any(p in {'.git','out','official','__pycache__'} for p in rel.parts) or path.suffix in {'.pyc','.pyo'}:
            continue
        need(not path.is_symlink(), 'SOURCE_LINK')
        if path.is_file():
            files[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    need('upstream.lock.json' in files and 'upgrade.sh' in files, 'SOURCE_INCOMPLETE')
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def verify_pair(before, after):
    old, new = tree_identity(before), tree_identity(after)
    need(old != new, 'CROSS_VERSION_REQUIRES_DISTINCT_TREES')
    return {'beforeTreeSha256':old,'afterTreeSha256':new,
            'officialArtifactsChanged':(Path(before)/'upstream.lock.json').read_bytes() !=
                                      (Path(after)/'upstream.lock.json').read_bytes()}


def isolated():
    need(os.geteuid() == 0 and Path('/run/systemd/system').is_dir(), 'DISPOSABLE_SYSTEMD_ROOT_REQUIRED')
    marker = Path('/run/bridge-disposable-test')
    need(marker.is_file() and not marker.is_symlink() and
         marker.read_text().strip() == 'CROSS_VERSION_ISOLATED_GUEST', 'DISPOSABLE_GUEST_REQUIRED')
    # No routable real-world interfaces. The fixture veths use documentation ranges.
    interfaces = {p.name for p in Path('/sys/class/net').iterdir()}
    need(interfaces <= {'lo','lan0','client0'} and 'lo' in interfaces, 'GUEST_NETWORK_NOT_ISOLATED')
    routes = subprocess.run(['ip','-j','route','show','table','all'], check=True,
                            capture_output=True, text=True, timeout=5)
    need(not any(x.get('dst') == 'default' for x in json.loads(routes.stdout)), 'GUEST_HAS_DEFAULT_ROUTE')


def run(before, after, settings, output):
    isolated()
    before, after, output = Path(before), Path(after), Path(output)
    need(before.resolve() != after.resolve() and not output.exists(), 'CROSS_VERSION_OUTPUT_OR_SOURCE')
    pair = verify_pair(before, after)
    output.mkdir(mode=0o700)
    rows = []
    passed = False
    def step(name, source, args):
        started = time.monotonic()
        r = subprocess.run(args, cwd=source, capture_output=True, timeout=600,
                           env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        # Only isolated synthetic sources are permitted; logs are still private.
        (output / (name + '.stdout')).write_bytes(r.stdout)
        (output / (name + '.stderr')).write_bytes(r.stderr)
        rows.append({'case':name,'treeSha256':tree_identity(source),'command':args,
                     'exitCode':r.returncode,'elapsedSeconds':time.monotonic()-started})
        need(r.returncode == 0, 'CROSS_VERSION_STEP_FAILED:' + name)
    try:
        step('old-install',before,['sh','install.sh','--settings',str(settings)])
        step('old-authorize',before,[sys.executable,'-B','-c',
            'from integration.packaging.onboarding import prepare_user;prepare_user()'])
        step('old-health',before,['sh','health-check.sh'])
        step('new-upgrade',after,['sh','upgrade.sh'])
        step('new-health',after,['sh','health-check.sh'])
        step('new-existing-account',after,[sys.executable,'-B','-c',
            'from integration.packaging.onboarding import existing_account;existing_account()'])
        # Data preservation and fault-injected rollback require dedicated VM
        # cases. Do not call a successful upgrade proof of those other checks.
        passed = True
    finally:
        result = {'passed':passed, **pair, 'checks':rows, 'scope':'REAL_DISTINCT_TREE_UPGRADE',
                  'dataplaneRollbackTest':'NOT_RUN','productionTest':'NOT_RUN'}
        (output/'cross-version-result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before',required=True,type=Path)
    p.add_argument('--after',required=True,type=Path)
    p.add_argument('--settings',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    print(json.dumps(run(a.before,a.after,a.settings,a.output),sort_keys=True))

if __name__=='__main__': main()
