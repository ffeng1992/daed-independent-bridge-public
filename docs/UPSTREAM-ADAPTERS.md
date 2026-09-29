# Pinned upstream adapters (phase 1)

`upstream.lock.json` is the artifact identity ledger. These are separate axes:

| Axis | Current identity | Adapter responsibility |
| --- | --- | --- |
| Official daed backend | `components.daed.version`, archive/member SHA-256 | GraphQL collection and source config semantics |
| daed's embedded core model | `components.daed.embedded_dae_commit` | Interpret fields and effective defaults returned by daed; it is not the running data plane |
| Standalone official DAE | `components.dae.version`, archive/member SHA-256 | Target fields, protocols, defaults and official `validate` |
| Bridge output | `0.2-m4-empty-groups` | Candidate text, IR, fingerprints, receipts and bundle format; this is not an upstream version |
| Official Web frontend | `webFrontend.version` and file hashes | Unmodified UI asset identity, independent of backend and DAE versions |

`bridge_m4.upstream_contracts` checks the current daed source model and DAE target model against the lock at import. Source and target fields remain separate in `contracts/m4/config-models.json`; target protocol limits remain in `protocol-models.json`. The GraphQL collector rejects schema drift before conversion. The converter does not silently drop a new field or assume a new protocol works. Public Web, DNS sync and service control do not implement upstream field maps.

The immutable `contracts/m4/extension-record-v1.json` is the exact v0.3.1 model contract, checked by a pinned SHA-256. A sealed v1 extension record is **validated with that contract**, including raw text, exact presence, values and existing hashes. Updating the current model cannot reinterpret it: direct merge/edit also requires the same source and target semantics for that section. Current contracts with the same contents still emit v1 bytes; candidate text, fingerprints, receipts and bundle IDs do not change. If a later contract adds a target-only field, `convert_record` accepts only an explicit `new-field-absent` rule and produces a new v2 record; the old generation stays sealed. Ownership, type, default or deletion changes fail closed until a separately reviewed semantic rule exists. A change to the bridge output format requires its own version and compatibility review, not an upstream version alias.

`contract_diagnostics` emits `FIELD_ADDED`, `FIELD_REMOVED`, `FIELD_TYPE_CHANGED`, `FIELD_DEFAULT_CHANGED` and `FIELD_OWNERSHIP_CHANGED` with side and field path. These diagnostics are a change inventory, **not** proof that a new official release is supported. Synthetic evolution tests exercise the failure behavior only.

The absent-field compatibility workarounds are pinned to two source-runtime models in `runtime_models.py`: official daed v2.1.1 and the historical fusion import. `auto_sniff_punt`, `max_cache_size` and `optimistic_stale_reply_ttl` are emitted only where raw source presence is absent. Explicit `false` and `0` remain explicit. The workaround exits only after a future source model and standalone DAE defaults have been reviewed and an explicit record conversion preserves behavior; it must not be removed merely because the upstream version string changes.

For the next **daed** update: pin its new archive/member hashes and embedded-core commit, compare GraphQL queries/schema and source config model, classify source fields and defaults, then test real GraphQL double snapshots and unchanged record interpretation. For the next **DAE** update: pin its new archive/member hashes, compare target config/protocol/default contracts, review extension ownership and workaround exit conditions, then run the actual new official `dae validate` and isolated data-plane acceptance. Either update may require a new bridge converter format and explicit conversion; neither can be claimed from synthetic tests.

Phase 2 is **inventory only**: examine where official standalone DAE could replace bridge compensations (runtime status, source defaults, policy sync and telemetry). No native capability switch, version selector, online switching or automatic upgrade system is implemented here.
