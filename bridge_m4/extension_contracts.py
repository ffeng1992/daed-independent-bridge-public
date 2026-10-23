"""Immutable archived contracts and section-scoped record identities.

Only contracts shipped as trusted project files are accepted. A record cannot
supply its own schema, and unknown contracts or semantic changes fail closed.
"""
import hashlib
import json
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1] / 'contracts/m4/record-contracts'
RULES = Path(__file__).resolve().parents[1] / 'contracts/m4/extension-compatibility.json'
SECTIONS = {'global': 'Global', 'dns': 'Dns', 'group': 'Group'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def section_model(contract, section):
    name = SECTIONS[section]
    return {'section': section, 'source': contract['source']['models'][name],
            'target': contract['target']['models'][name]}


def section_identity(contract, section):
    return identity(section_model(contract, section))


def _hash(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def resolve(record, current, legacy, *, archive=ARCHIVE):
    version, section = record['schemaVersion'], record['section']
    if version == 1:
        return legacy
    if version == 2:
        pin = record.get('contractSha256')
        if not _hash(pin):
            raise ValueError('EXTENSION_CONTRACT_IDENTITY')
        for model in (current, legacy):
            if identity(model) == pin:
                return model
        path = Path(archive) / (pin + '.json')
        if path.is_symlink():
            raise ValueError('EXTENSION_CONTRACT_AUTHORITY')
        model = json.loads(path.read_text())
        if identity(model) != pin:
            raise ValueError('EXTENSION_CONTRACT_IDENTITY')
        return model
    if version != 3:
        raise ValueError('INVALID_EXTENSION_RECORD')
    pin = record.get('sectionContractSha256')
    if not _hash(pin):
        raise ValueError('EXTENSION_CONTRACT_IDENTITY')
    for model in (current, legacy):
        if section_identity(model, section) == pin:
            return model
    # Archives are small, immutable configuration contracts, not source history.
    # A bounded search prevents an unbounded archive from affecting requests.
    paths = sorted(Path(archive).glob('*.json'))
    if len(paths) > 32:
        raise ValueError('EXTENSION_CONTRACT_ARCHIVE_LIMIT')
    for path in paths:
        if path.is_symlink() or not _hash(path.stem) or path.stat().st_size > 256 * 1024:
            raise ValueError('EXTENSION_CONTRACT_AUTHORITY')
        model = json.loads(path.read_text())
        if identity(model) != path.stem:
            raise ValueError('EXTENSION_CONTRACT_IDENTITY')
        if section_identity(model, section) == pin:
            return model
    raise ValueError('EXTENSION_CONTRACT_UNAVAILABLE')


def compatible(section, old, new, *, rules_path=RULES):
    """Exact section semantics need no migration, regardless of unrelated sections.

    Optional additions require a reviewed, shipped rule. Defaults, requiredness,
    repeatability, types, removals and ownership changes are never guessed.
    """
    if section_model(old, section) == section_model(new, section):
        return True
    try:
        policy = json.loads(Path(rules_path).read_text())
    except FileNotFoundError:
        return False
    if (type(policy) is not dict or set(policy) != {'schemaVersion', 'rules'} or
            type(policy['schemaVersion']) is not int or policy['schemaVersion'] != 1 or
            type(policy['rules']) is not dict):
        raise ValueError('EXTENSION_COMPATIBILITY_SCHEMA')
    rule = policy['rules'].get(section_identity(old, section) + ':' + section_identity(new, section))
    if type(rule) is not dict or set(rule) != {'section', 'addedAbsentFields', 'review'}:
        return False
    if rule['section'] != section or type(rule['review']) is not str or not rule['review'].strip():
        return False
    before, after = section_model(old, section), section_model(new, section)
    # Source-owned fields must not move; all existing target semantics must match.
    if before['source'] != after['source']:
        return False
    if any(after['target'].get(k) != value for k, value in before['target'].items()):
        return False
    added = set(after['target']) - set(before['target'])
    fields = rule['addedAbsentFields']
    return (type(fields) is list and all(type(x) is str for x in fields) and
            len(fields) == len(set(fields)) and set(fields) == added and bool(added) and
            all(after['target'][key].get('required') is False for key in added))


def record_contract(record, current, legacy):
    from .extensions import CompatibilityError
    try:
        return resolve(record, current, legacy)
    except (OSError, KeyError, TypeError, ValueError, RecursionError):
        raise CompatibilityError('EXTENSION_CONTRACT_UNAVAILABLE', record.get('section', '$')) from None


def require_compatible(record, current, legacy):
    from .extensions import need
    old = record_contract(record, current, legacy)
    need(compatible(record['section'], old, current),
         'EXTENSION_CONTRACT_CONVERSION_REQUIRED', record['section'])
    return old


def projected_fields(record, current, legacy):
    """Read-only projection of approved absent additions; sealed bytes stay intact."""
    from .upstream_contracts import extension_fields
    require_compatible(record, current, legacy)
    specs = extension_fields(record['section'], current)
    if not set(record['fields']) <= set(specs):
        raise ValueError('EXTENSION_OWNERSHIP_CONFLICT')
    return {key: record['fields'].get(key, {'present': False}) for key in sorted(specs)}
