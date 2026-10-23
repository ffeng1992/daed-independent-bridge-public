"""Deterministic inventory of the shipped management source payload.

No old-version target hashes: installed inventory is its own authority. This
scope deliberately excludes official artifacts, dependencies, units and DNS
implementation files owned by an existing deployment.
"""
import hashlib
import json
from pathlib import Path
import sys

PACKAGES = ('bridge_m1', 'bridge_m2', 'bridge_m4', 'contracts', 'queries')
SCRIPTS = ('scripts/m4_install.py', 'scripts/management_recovery.py',
           'scripts/release_geodata_update.py')
RUNTIME_DEPENDENCIES = ('graphql', 'jsonschema')


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def eligible(name):
    return name.startswith(tuple(p + '/' for p in PACKAGES)) or name in SCRIPTS


def files(root):
    root = Path(root)
    paths = []
    for package in PACKAGES:
        folder = root / package
        if package == 'queries' and not folder.exists():
            continue
        need(folder.is_dir() and not folder.is_symlink(), 'PACKAGE_DIRECTORY')
        for p in sorted(folder.rglob('*')):
            if '__pycache__' in p.parts or p.suffix in {'.pyc', '.pyo'}:
                continue
            need(not p.is_symlink(), 'PACKAGE_SOURCE_LINK')
            if p.is_file():
                paths.append(p.relative_to(root).as_posix())
    paths.extend(SCRIPTS)
    return sorted(paths)


def generate(root):
    root = Path(root)
    inventory = {}
    for name in files(root):
        p = root / name
        need(p.is_file() and not p.is_symlink(), 'PACKAGE_SOURCE_LINK')
        inventory[name] = {'sha256': sha(p.read_bytes()), 'mode': 0o644,
                           'owner': 'root', 'group': 'root'}
    tooling = {}
    for p in sorted((root/'scripts').rglob('*')):
        if '__pycache__' not in p.parts and p.suffix in {'.py','.json'} and p.is_file():
            need(not p.is_symlink(), 'PACKAGE_SOURCE_LINK')
            tooling[p.relative_to(root).as_posix()] = {'sha256':sha(p.read_bytes()), 'mode':0o644, 'owner':'root', 'group':'root'}
    # These are deployment/data contracts, not an interchangeable version label.
    return {'schemaVersion': 1, 'kind': 'BRIDGE_MANAGEMENT_SOURCE',
            'installSchemaVersions': [1], 'extensionSchemaVersions': [1, 2],
            'deploymentTypes': ['native-dae', 'bridge-managed', 'external-policy'],
            'upstreamLockSha256': sha((root / 'upstream.lock.json').read_bytes()),
            'dependencies': {'pythonMinimum': [3, 11], 'modules': list(RUNTIME_DEPENDENCIES)},
            'files': inventory, 'installerFiles': tooling}


def verify(root, package):
    need(package == generate(root), 'PACKAGE_INTEGRITY')
    need(sys.version_info >= (3, 11), 'PACKAGE_PYTHON_DEPENDENCY')
    return package


def dependencies():
    """Import from the installed vendor path; never download or mutate it."""
    import importlib
    for name in RUNTIME_DEPENDENCIES:
        try:
            importlib.import_module(name)
        except ImportError:
            raise RuntimeError('PACKAGE_DEPENDENCY_MISSING:' + name) from None
