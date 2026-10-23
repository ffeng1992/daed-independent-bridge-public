"""Active DAT authority, separate from the installed program inventory.

Program startup need not read a retired fallback. Root helper operations still
verify the selected data, and installation/rollback audits can verify everything.
"""
import os
from pathlib import Path

ASSET_FILES = frozenset('/opt/bridge-official/assets/' + n
                        for n in ('geoip.dat', 'geosite.dat'))


def verify_active_assets(installed):
    from . import geodata
    from bridge_m2.security import directory, read_at, check, digest
    folder, _ = geodata.generation()
    if folder is not None:
        identity = geodata.current_id()
        hashes = geodata.selected_hashes_from_folder(folder)
        check(identity == folder.name and geodata.current_id() == identity, 'GEODATA_SELECTED_CHANGED')
        return hashes
    observed = {}
    for name in sorted(ASSET_FILES):
        check(name in installed['files'], 'INSTALL_ASSET_IDENTITY_MISSING')
        pin = installed['files'][name]
        path = Path(name)
        fd = directory(path.parent, 0, 0, 0o755)
        try:
            body = read_at(fd, path.name, 0, 0, pin['mode'], limit=150 * 1024 * 1024)
        finally:
            os.close(fd)
        check(digest(body) == pin['sha256'], 'INSTALL_ACTIVE_ASSET_IDENTITY')
        observed[path.name] = digest(body)
    check(geodata.current_id() is None, 'GEODATA_SELECTED_CHANGED')
    return observed
