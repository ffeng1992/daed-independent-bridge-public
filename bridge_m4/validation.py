"""One fixed official validator/asset environment shared by Web and helper."""
from pathlib import Path
import subprocess
from bridge_m2.control import ENV
from bridge_m2.security import check,digest
from .upstream_contracts import DAE_ARTIFACT

BINARY=Path('/opt/bridge-official/dae')
ASSETS=Path('/opt/bridge-official/assets')
DAE_ENV={**ENV,'DAE_LOCATION_ASSET':str(ASSETS)}


def asset_identity():
    pins={p['path']:p for p in DAE_ARTIFACT['archive_members']}
    observed={}
    for name in ('geoip.dat','geosite.dat'):
        body=(ASSETS/name).read_bytes();observed[name]=digest(body)
        check(len(body)==pins[name]['size'] and observed[name]==pins[name]['sha256'],'OFFICIAL_ASSET_HASH')
    return observed


def validate(candidate,expected):
    before=asset_identity()
    check(digest(BINARY.read_bytes())==expected,'VALIDATOR_HASH')
    result=subprocess.run([str(BINARY),'validate','-c',str(candidate)],env=DAE_ENV,capture_output=True,timeout=30)
    check(digest(BINARY.read_bytes())==expected,'VALIDATOR_CHANGED')
    check(asset_identity()==before,'OFFICIAL_ASSET_CHANGED')
    check(result.returncode==0,'VALIDATE_FAILED')
    return {'exitCode':result.returncode,'binarySha256':expected,'assetSha256':before,'output':'[REDACTED]'}
