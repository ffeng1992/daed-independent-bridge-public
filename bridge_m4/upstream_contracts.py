"""Pinned source and target contracts; no runtime version guessing.

The record-v1 contract is immutable history. A later official contract may be
loaded as the current adapter, but cannot reinterpret a sealed v1 record.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'upstream.lock.json').read_text())
CONFIG = json.loads((ROOT / 'contracts/m4/config-models.json').read_text())
PROTOCOLS = json.loads((ROOT / 'contracts/m4/protocol-models.json').read_text())
LEGACY_RECORD_SHA256 = '00cb5a54b8f23b3553daf5493870e517918b9deefbb3c74ab8acd5d40d00b183'
_legacy_bytes = (ROOT / 'contracts/m4/extension-record-v1.json').read_bytes()
if hashlib.sha256(_legacy_bytes).hexdigest() != LEGACY_RECORD_SHA256:
    raise RuntimeError('LEGACY_EXTENSION_CONTRACT_CHANGED')
LEGACY_RECORD = json.loads(_legacy_bytes)

if (CONFIG['source']['daed'] != LOCK['components']['daed']['version'] or
        CONFIG['source']['coreCommit'] != LOCK['components']['daed']['embedded_dae_commit'] or
        CONFIG['target']['dae'] != LOCK['components']['dae']['version'] or
        CONFIG['target']['commit'] != LOCK['components']['dae']['commit']):
    raise RuntimeError('UPSTREAM_CONTRACT_LOCK_MISMATCH')

DAED_VERSION = LOCK['components']['daed']['version']
EMBEDDED_CORE_COMMIT = LOCK['components']['daed']['embedded_dae_commit']
DAE_VERSION = LOCK['components']['dae']['version']
DAED_ARTIFACT = LOCK['components']['daed']  # archive and member identities
DAE_ARTIFACT = LOCK['components']['dae']
WEB_ARTIFACT = LOCK['webFrontend']
DAE_TARGET = 'dae-' + DAE_VERSION + '-' + LOCK['components']['dae']['platform']
BRIDGE_FORMAT = '0.2-m4-empty-groups'  # sealed candidate/receipt converter format
SOURCE_MODELS = CONFIG['source']['models']
TARGET_MODELS = CONFIG['target']['models']
TARGET_PROTOCOLS = PROTOCOLS['target']['entries']


def official_member_sha(component, member):
    """Resolve a pinned official archive member without duplicating lock parsing."""
    matches = [item['sha256'] for item in LOCK['components'][component]['archive_members']
               if item['path'] == member]
    if len(matches) != 1:
        raise RuntimeError('OFFICIAL_MEMBER_IDENTITY_MISSING')
    return matches[0]


def extension_fields(section, contract=CONFIG):
    """Return fields owned by the target adapter, not by official daed."""
    name = {'global': 'Global', 'dns': 'Dns', 'group': 'Group'}[section]
    target = contract['target']['models'][name]
    if section == 'group':
        return {key: value for key, value in target.items() if key not in ('filter', 'policy')}
    source = contract['source']['models'][name]
    return {key: value for key, value in target.items() if key not in source}


def same_section_contract(section, old, new):
    """A sealed record may be used directly only under its original semantics."""
    name = {'global': 'Global', 'dns': 'Dns', 'group': 'Group'}[section]
    return all(old[side]['models'][name] == new[side]['models'][name]
               for side in ('source', 'target'))


def contract_diagnostics(old, new):
    """Classify synthetic or future model drift without claiming compatibility."""
    result = []
    for side in ('source', 'target'):
        before = old[side]['models']; after = new[side]['models']
        for section in sorted(set(before) | set(after)):
            a = before.get(section, {}); b = after.get(section, {})
            for field in sorted(set(a) | set(b)):
                path = section + '.' + field
                if field not in a:
                    result.append({'side': side, 'path': path, 'code': 'FIELD_ADDED'})
                elif field not in b:
                    result.append({'side': side, 'path': path, 'code': 'FIELD_REMOVED'})
                else:
                    for attr, code in (('type', 'FIELD_TYPE_CHANGED'), ('default', 'FIELD_DEFAULT_CHANGED')):
                        # An omitted default and an explicit null have distinct semantics.
                        if (attr in a[field], a[field].get(attr)) != (attr in b[field], b[field].get(attr)):
                            result.append({'side': side, 'path': path, 'code': code})
    for section in ('Global', 'Dns', 'Group'):
        fields = set()
        for contract in (old, new):
            fields.update(contract['source']['models'].get(section, {}))
            fields.update(contract['target']['models'].get(section, {}))
        for field in sorted(fields):
            def owner(contract):
                if field in contract['source']['models'].get(section, {}): return 'daed'
                if field in contract['target']['models'].get(section, {}): return 'bridge'
                return None
            if owner(old) != owner(new):
                result.append({'side': 'ownership', 'path': section + '.' + field, 'code': 'FIELD_OWNERSHIP_CHANGED'})
    return result
