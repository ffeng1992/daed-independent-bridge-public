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


def validate(candidate, expected, *, assets_override=None):
    before=asset_identity()
    before_selected = verified_selected_hashes(assets_override)
    check(digest(BINARY.read_bytes())==expected,'VALIDATOR_HASH')
    result=subprocess.run([str(BINARY),'validate','-c',str(candidate)],env=runtime_asset_env(assets_override),capture_output=True,timeout=30)
    check(digest(BINARY.read_bytes())==expected,'VALIDATOR_CHANGED')
    check(asset_identity()==before,'OFFICIAL_ASSET_CHANGED')
    check(verified_selected_hashes(assets_override) == before_selected, 'GEODATA_SELECTED_CHANGED')
    check(result.returncode==0,'VALIDATE_FAILED')
    return {'exitCode':result.returncode,'binarySha256':expected,'assetSha256':before,'output':'[REDACTED]'}


# Extension added by the Bridge geodata timer. Original asset_identity() and
# its current production release pins above are deliberately UNCHANGED.
def verified_selected_hashes(assets_override=None):
    from . import geodata
    if assets_override is not None:
        path, _ = geodata.verify_generation_folder(assets_override)
    else:
        path = geodata.selected_dir(official=Path(DAE_ENV['DAE_LOCATION_ASSET']))
    return {name: geodata.sha(geodata.verify_file(path / name,
                 max_size=geodata.LIMITS[name])) for name in geodata.DATASETS}


def runtime_asset_env(assets_override=None):
    # Enforce the production's existing fixed release/hash identity FIRST.
    asset_identity()
    from . import geodata
    if assets_override is not None:
        chosen, _ = geodata.verify_generation_folder(assets_override)
    else:
        chosen = geodata.selected_dir(official=Path(DAE_ENV['DAE_LOCATION_ASSET']))
    return {**DAE_ENV, 'DAE_LOCATION_ASSET': str(chosen)}
