"""Optional existing-production DNS integration; never starts any service.

The policy generator, geodata, dnsdist configuration and ingress state belong to
existing DNS infrastructure. They are neither imported into Git nor uninstalled.
"""
from pathlib import Path
import shutil
import subprocess

UNITS=('independent-dns-sync.service','independent-dns-sync.timer',
       'independent-policy-sync.service','independent-policy-sync.timer')
SCRIPT='/etc/dae-dns-repair/sync_policy_independent.py'
LEGACY_UNITS=('daed.service','daed-dnsdist-sync.service','daed-dnsdist-sync-tc.service',
    'daed-dnsdist-sync.path','dae-policy-sync.service','dae-policy-sync.timer',
    'daed-node-v3-background.service','daed-node-v3-background.timer',
    'daed-node-v3-manual.service','daed-node-v3-nightly.service','daed-node-v3-nightly.timer',
    'daed-node-v3-journal-watchdog@.service','daed-node-v3-journal-watchdog@.timer')

def payload(root):
    files={'/etc/systemd/system/'+name:((root/'deployment/m4/units'/name).read_bytes(),0o644) for name in UNITS}
    files[SCRIPT]=((root/'deployment/m4/production/sync_policy_independent.py').read_bytes(),0o644)
    return files

def prerequisites():
    for name in ('/etc/dae-dns-repair/build_dns.py','/usr/share/daed/geosite.dat',
                 '/var/lib/dae-ingress-sync/state.json','/etc/dae-dns-repair/policy-dns.conf',
                 '/usr/local/lib/daed-dnsdist-sync/daed_dnsdist_sync/core.py'):
        if not Path(name).is_file():raise RuntimeError('PRODUCTION_DNS_DEPENDENCY_MISSING')

def retire_legacy_units(root=Path('/'),run=subprocess.run):
    """Only inactive retired entrypoints; no binaries/databases/DNS assets deleted."""
    found=[]
    for name in LEGACY_UNITS:
        paths=[root/'etc/systemd/system'/name,root/'usr/lib/systemd/system'/name]
        if not any(p.exists() or p.is_symlink() or Path(str(p)+'.d').exists() for p in paths):continue
        if '@.' not in name:
            r=run(['/usr/bin/systemctl','show',name,'--property=ActiveState,MainPID'],capture_output=True,check=True,timeout=20)
            values=dict(line.split('=',1) for line in r.stdout.decode().splitlines() if '=' in line)
            if values.get('ActiveState')!='inactive' or values.get('MainPID','0')!='0':
                raise RuntimeError('LEGACY_SERVICE_NOT_INACTIVE')
        found.append((name,paths))
    # Complete all inactivity checks before removing any entrypoint.
    for name,paths in found:
        run(['/usr/bin/systemctl','disable',name],capture_output=True,check=True,timeout=20)
        for path in paths:
            if path.is_symlink() or path.is_file():path.unlink()
            drop=Path(str(path)+'.d')
            if drop.is_symlink():drop.unlink()
            elif drop.is_dir():shutil.rmtree(drop)
    return [name for name,_ in found]
