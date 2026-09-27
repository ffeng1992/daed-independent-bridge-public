"""Source release tarball from an explicit committed allowlist, without private data."""
import gzip
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
ROOT=Path(__file__).resolve().parents[1]
PREFIXES=('bridge_m1/','bridge_m2/','bridge_m4/','contracts/','deployment/m4/','deployment/release/')
EXACT={'README.md','LICENSE','VERSION','THIRD_PARTY.md','PUBLIC_EXPORT.md','.public-source.json','upstream.lock.json','install.sh','upgrade.sh','uninstall.sh','health-check.sh',
       'scripts/__init__.py','scripts/m4_install.py','scripts/m4_install_transaction.py',
       'scripts/m4_package.py','scripts/m4_assets.py','scripts/m4_production_dns.py'}

def included(name):
    return name in EXACT or (name.startswith(PREFIXES) and name not in {'deployment/m4/production/files.json','deployment/m4/production/README.md','bridge_m4/migrate.py','bridge_m4/private_inputs.py','bridge_m4/migration.py','bridge_m4/migration_journal.py'}) or (name.startswith('scripts/release_') and name.endswith('.py'))

def main():
    subprocess.run(['git','diff','--exit-code'],cwd=ROOT,check=True)
    subprocess.run(['git','diff','--cached','--exit-code'],cwd=ROOT,check=True)
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',sha],cwd=ROOT,text=True).splitlines()
    out=ROOT/'out/release';out.mkdir(parents=True,exist_ok=True)
    target=out/('daed-independent-bridge-'+sha+'.tar.gz')
    with target.open('wb') as stream, gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0) as compressed, tarfile.open(fileobj=compressed,mode='w') as archive:
        for name in sorted(filter(included,names)):
            body=subprocess.check_output(['git','show',sha+':'+name],cwd=ROOT)
            info=tarfile.TarInfo('daed-independent-bridge/'+name)
            info.size=len(body);info.mode=0o755 if name.endswith('.sh') else 0o644
            archive.addfile(info,io.BytesIO(body))
    (out/'SHA256SUMS').write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name+'\n')
    print(str(target))
if __name__=='__main__':main()
