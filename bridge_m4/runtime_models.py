"""Explicit effective defaults for pinned source runtime models.

V1 records retain their documented official-daed model. V2 imports bind the
chosen runtime model into the hashed extension document; never infer it from
an untrusted database name. Raw field absence remains in each lossless record.
"""
from .extensions import need

OFFICIAL = 'official-daed-v2.1.1'  # sealed v1 extension record semantics
FUSION = 'fusion-7ed6de2eac8cff8b0c8468e9445db1db58ef3190'
DEFAULTS = {
    OFFICIAL: {'global.auto_sniff_punt':False, 'dns.max_cache_size':0, 'dns.optimistic_stale_reply_ttl':0},
    FUSION: {'global.auto_sniff_punt':True, 'dns.max_cache_size':65536, 'dns.optimistic_stale_reply_ttl':30},
}

def model(extensions):
    version=extensions.get('schemaVersion',1)
    need(type(version) is int and version in (1,2),'EXTENSION_VERSION','extensions.schemaVersion')
    if version==1:
        need('sourceRuntimeModel' not in extensions,'EXTENSION_VERSION','extensions.sourceRuntimeModel')
        return OFFICIAL
    name=extensions.get('sourceRuntimeModel')
    need(type(name) is str and name in DEFAULTS,'UNKNOWN_SOURCE_RUNTIME_MODEL','extensions.sourceRuntimeModel')
    return name
