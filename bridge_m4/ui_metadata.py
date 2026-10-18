"""Read-only, authenticated UI projection; never binds, edits or applies.

Use only from the existing protected Web dispatch. Object names and field
contracts are returned, never node links, source configuration or credentials.
The caller's existing collector uses backend.token, not the Web session secret.
"""
import base64
import re
import time

from .runtime_bundle import fingerprints
from .upstream_contracts import DAED_VERSION, DAE_VERSION, extension_fields


def _profile_id(encoded):
    if type(encoded) is not str or len(encoded) > 256:
        raise ValueError('UI_PROFILE_ID')
    decoded = base64.b64decode(encoded + '=' * (-len(encoded) % 4), validate=True).decode('ascii')
    if not re.fullmatch(r'cursor[0-9]+', decoded):
        raise ValueError('UI_PROFILE_ID')
    return decoded[6:]


def metadata(runtime, token, *, now=None):
    """Return a complete source projection without changing persistent state.

    snapshot() may construct missing extension records IN MEMORY. This does not
    call ExtensionStore.bind_profiles/commit. Bound flags use the stored records.
    Source-vs-running comparison is withheld if the runtime identity changed
    during collection or cannot be verified.
    """
    with runtime.lock:
        before = runtime.status()
        source, proof, effective, generation = runtime.snapshot(token)
        latest, stored = runtime.store.load()
        if latest != generation:
            raise ValueError('UI_EXTENSION_CHANGED')
        after = runtime.status()
        collection_stable = (proof.get('beforeSha256') is not None
                             and proof.get('beforeSha256') == proof.get('afterSha256'))
        keys = ('activeBundle', 'configSha256', 'sourceFingerprint', 'InvocationID')
        coherent = (collection_stable and before.get('identityVerified') is True
                    and after.get('identityVerified') is True
                    and all(before.get(k) == after.get(k) for k in keys)
                    and type(after.get('sourceFingerprint')) is str)
        pins = fingerprints(source, effective)
        profiles = {}
        specs = {}
        for kind, section in (('configs', 'global'), ('dnss', 'dns'), ('groups', 'group')):
            saved = stored['extensions']['records'].get(section, {})
            rows = []
            for item in source['metadata'][kind]:
                ident = _profile_id(item['id'])
                name = item.get('name')
                if type(name) is not str:
                    raise ValueError('UI_PROFILE_NAME')
                rows.append({'id': ident, 'name': name,
                             'selected': item.get('selected') is True,
                             'bound': ident in saved})
            profiles[section] = rows
            specs[section] = {
                field: {'type': value['type']}  # No guessed effective defaults.
                for field, value in extension_fields(section).items()
            }
        return {
            'schemaVersion': 1,
            'observedAt': int(time.time()) if now is None else int(now),
            'generation': generation,
            'profiles': profiles,
            'specs': specs,
            'nodeCount': len(source['nodes']),
            'groupCount': len(source['metadata']['groups']),
            'versions': {'daed': DAED_VERSION, 'dae': DAE_VERSION,
                         'scope': 'installed-contract'},
            'sourceFingerprint': pins['sourceSha256'],
            'runningSourceFingerprint': after.get('sourceFingerprint'),
            'comparisonVerified': coherent,
            'modified': (pins['sourceSha256'] != after['sourceFingerprint']) if coherent else None,
            'collectionStable': collection_stable,
        }
