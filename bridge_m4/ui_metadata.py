"""Authenticated, read-only editor projection (schema 2).

The editor's names, types, bound flags and persisted fields share one generation.
No source configuration, node links or credentials are exposed. This module never
binds, saves, previews or applies; existing Runtime/Store remain the only writers.
"""
import base64
import copy
import re
import time

from .runtime_bundle import fingerprints
from .upstream_contracts import DAED_VERSION, DAE_VERSION, extension_fields, CONFIG, LEGACY_RECORD
from .extension_contracts import projected_fields

HASH = re.compile(r'[a-f0-9]{64}')
KINDS = (('configs', 'global'), ('dnss', 'dns'), ('groups', 'group'))


def _hash(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def _profile_id(encoded):
    if type(encoded) is not str or len(encoded) > 256:
        raise ValueError('UI_PROFILE_ID')
    decoded = base64.b64decode(encoded + '=' * (-len(encoded) % 4), validate=True).decode('ascii')
    if not re.fullmatch(r'cursor[0-9]+', decoded):
        raise ValueError('UI_PROFILE_ID')
    return decoded[6:]


def _identity(state):
    """Only a complete, error-free running identity proves a comparison."""
    return (type(state) is dict and not state.get('error')
            and state.get('identityVerified') is True
            and state.get('state') == 'running'
            and all(_hash(state.get(k)) for k in
                    ('activeBundle', 'configSha256', 'sourceFingerprint'))
            and type(state.get('InvocationID')) is str
            and re.fullmatch(r'[a-f0-9]{32}', state['InvocationID']) is not None)


def _field_state(value):
    # Copy only the public field-state schema, not a sealed record/sourceText.
    if type(value) is not dict or type(value.get('present')) is not bool:
        raise ValueError('UI_FIELD_STATE')
    if set(value) != ({'present', 'value'} if value['present'] else {'present'}):
        raise ValueError('UI_FIELD_STATE')
    return copy.deepcopy(value)


def metadata(runtime, token, *, now=None):
    """Read one coherent editor generation. Unknown never means unmodified.

    snapshot() only constructs absent new profiles in memory. load() validates
    sealed persisted records using their existing contracts; they are not
    reinterpreted or written by this presentation layer.
    """
    with runtime.lock:
        before = runtime.status()
        source, proof, effective, generation = runtime.snapshot(token)
        latest, stored = runtime.store.load()
        if latest != generation or not _hash(generation):
            raise ValueError('UI_EXTENSION_CHANGED')
        after = runtime.status()
        collection_stable = (_hash(proof.get('beforeSha256'))
                             and proof.get('beforeSha256') == proof.get('afterSha256'))
        keys = ('activeBundle', 'configSha256', 'sourceFingerprint', 'InvocationID')
        coherent = (collection_stable and _identity(before) and _identity(after)
                    and all(before[k] == after[k] for k in keys))
        pins = fingerprints(source, effective)
        if not _hash(pins.get('sourceSha256')):
            raise ValueError('UI_SOURCE_FINGERPRINT')
        profiles, specs, records, orphan_counts = {}, {}, {}, {}
        for kind, section in KINDS:
            saved = stored['extensions']['records'].get(section, {})
            if type(saved) is not dict or type(source['metadata'][kind]) is not list:
                raise ValueError('UI_PROFILE_SET')
            rows, public_fields, seen = [], {}, set()
            for item in source['metadata'][kind]:
                ident = _profile_id(item['id'])
                if ident in seen:
                    raise ValueError('UI_DUPLICATE_PROFILE')
                seen.add(ident)
                name = item.get('name')
                if type(name) is not str:
                    raise ValueError('UI_PROFILE_NAME')
                bound = ident in saved
                rows.append({'id': ident, 'name': name,
                             'selected': item.get('selected') is True, 'bound': bound})
                if bound:
                    record = saved[ident]
                    if type(record) is not dict or type(record.get('fields')) is not dict:
                        raise ValueError('UI_FIELD_STATE')
                    public_fields[ident] = {field: _field_state(state)
                                           for field, state in projected_fields(record, CONFIG, LEGACY_RECORD).items()}
            profiles[section], records[section] = rows, public_fields
            orphan_counts[section] = len(set(saved) - seen)
            specs[section] = {
                field: {'type': value['type']}
                for field, value in extension_fields(section).items()
            }
        # A Store writer in another process does not share runtime.lock.
        # Detect a generation change even after projection work; frontend still
        # supplies CAS on every write, so a later change is safely rejected.
        final_generation, _ = runtime.store.load()
        if final_generation != generation:
            raise ValueError('UI_EXTENSION_CHANGED')
        return {
            'schemaVersion': 2,
            'observedAt': int(time.time()) if now is None else int(now),
            'generation': generation, 'profiles': profiles, 'specs': specs,
            'records': records, 'orphanRecordCounts': orphan_counts,
            'nodeCount': len(source['nodes']),
            'groupCount': len(source['metadata']['groups']),
            'versions': {'daed': DAED_VERSION, 'dae': DAE_VERSION,
                         'scope': 'installed-contract'},
            'sourceFingerprint': pins['sourceSha256'],
            'runningSourceFingerprint': after.get('sourceFingerprint') if _hash(after.get('sourceFingerprint')) else None,
            'runningIdentity': {k: after.get(k) for k in keys} if _identity(after) else None,
            'comparisonVerified': coherent,
            'modified': pins['sourceSha256'] != after['sourceFingerprint'] if coherent else None,
            'collectionStable': collection_stable,
        }
