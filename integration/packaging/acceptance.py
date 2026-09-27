"""Clean Debian lifecycle with synthetic DNS confined to the guest network."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
SOURCE=Path('/opt/release-source');EVIDENCE=Path('/evidence');checks=[]


def run(args):
    return subprocess.run(args,cwd=SOURCE,check=True,capture_output=True,timeout=300)


def case(name,args):
    r=run(args)
    if name=='install':
        records=[json.loads(line) for line in r.stdout.decode().splitlines() if line.startswith('{')]
        if not any(v.get('managementReady') is True and v.get('setupRequired') is True and v.get('dataplaneReady') is False and v.get('daedWebGraphQL') is True for v in records):
            raise RuntimeError('FIRST_SETUP_EVIDENCE_MISSING')
    elif name.startswith('health-') or name in ('upgrade','reinstall','repeat-install'):
        records=[json.loads(line) for line in r.stdout.decode().splitlines() if line.startswith('{')]
        if not any(v.get('daedWebHTTP') is True and v.get('daedWebGraphQL') is True and v.get('onlyIndependentDAE') is True and v.get('webIdentityMatches') is True for v in records):
            raise RuntimeError('WEB_OR_DATAPLANE_EVIDENCE_MISSING')
    checks.append({'case':name,'passed':True})
    print(name+': PASS',flush=True)
    return r


def retained():
    result={}
    for directory in ('/etc/daed-independent-bridge','/var/lib/bridge-daed','/var/lib/bridge-m4-client/extensions','/opt/bridge-official/assets'):
        for p in Path(directory).rglob('*'):
            if p.is_file() and p.name!='install.json':result[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def main():
    passed=False;stage='setup'
    try:
        if sorted(p.name for p in Path('/sys/class/net').iterdir())!=['lo']:raise RuntimeError('ISOLATION_REQUIRED')
        run(['ip','link','add','lan0','type','veth','peer','name','client0'])
        run(['ip','addr','add','192.0.2.1/24','dev','lan0']);run(['ip','link','set','lan0','up']);run(['ip','link','set','client0','up'])
        # Fixed in-VM upstream. No public names, credentials, proxy endpoints or egress.
        endpoint=SOURCE/'integration/packaging/dns_fixture.py'
        fixture=subprocess.Popen(['python3',str(endpoint)])
        settings=Path('/run/packaging-settings.json')
        settings.write_text(json.dumps({'lanAddress':'192.0.2.1','lanNetwork':'192.0.2.0/24','lanInterface':'lan0',
            'upstream':'127.0.0.1:15353','dnsName':'health.test.invalid','webAddress':'127.0.0.1'}))
        time.sleep(1)
        stages=[('install',['sh','install.sh','--settings',str(settings)]),
                ('health-install',['sh','health-check.sh']),('repeat-install',['sh','install.sh']),
                ('upgrade',['sh','upgrade.sh']),('health-upgrade',['sh','health-check.sh'])]
        for stage,args in stages:
            case(stage,args)
            from integration.packaging.onboarding import prepare_user,existing_account
            if stage=='install':
                stage='official-first-account-and-authorization'
                prepare_user()
                checks.append({'case':stage,'passed':True})
            existing_account()
        # Stop before snapshotting to avoid treating normal SQLite WAL flush as corruption.
        from scripts.release_lifecycle import stop
        stop();before=retained()
        stage='uninstall-retain';case(stage,['sh','uninstall.sh'])
        if retained()!=before:raise RuntimeError('RETAINED_DATA_CHANGED')
        checks.append({'case':'persistent-data-retained','passed':True})
        stage='reinstall';case(stage,['sh','install.sh'])
        stage='health-reinstall';case(stage,['sh','health-check.sh']);existing_account()
        stage='purge';case(stage,['sh','uninstall.sh','--purge','--confirm-purge','DELETE-INDEPENDENT-BRIDGE'])
        from scripts.release_lifecycle import DATA
        if any(p.exists() for p in DATA):raise RuntimeError('PURGE_DATA_REMAINS')
        from scripts.release_payload import UNITS
        for n in (*UNITS,'dae.service','daed-api.service','independent-bridge.service','independent-dns-sync.timer','independent-policy-sync.timer'):
            if Path('/etc/systemd/system',n).exists():raise RuntimeError('UNIT_REMAINS')
        checks.append({'case':'purge-complete','passed':True});fixture.terminate();fixture.wait(timeout=5)
        passed=True
    except Exception as exc:
        # Logs from synthetic inputs only; do not print generated admin credentials.
        checks.append({'case':stage,'passed':False,'errorType':type(exc).__name__})
        if isinstance(exc,subprocess.CalledProcessError):
            (EVIDENCE/'packaging-error.log').write_bytes(exc.stdout[-8000:]+exc.stderr[-8000:])
        else:(EVIDENCE/'packaging-error.log').write_text(str(exc))
        for unit in ('daed-web','dae','daed-api','independent-bridge','bridge-helper','bridge-attestor','bridge-policy-dns','bridge-lan-dns','independent-dns-sync','independent-policy-sync'):
            r=subprocess.run(['journalctl','-u',unit,'--no-pager','-n','20'],capture_output=True)
            (EVIDENCE/(unit+'.log')).write_bytes(r.stdout)
    finally:
        (EVIDENCE/'packaging-result.json').write_text(json.dumps({'passed':passed,'checkoutSha':(EVIDENCE/'candidate-commit.txt').read_text().strip(),'checks':checks,'officialWebVersion':'1.28.0','webChecks':'HTTP_OFFICIAL_ASSET_HASH_GRAPHQL_BRIDGE_IDENTITY_SINGLE_DAE'},indent=2))
    if not passed:raise SystemExit(1)
if __name__=='__main__':main()
