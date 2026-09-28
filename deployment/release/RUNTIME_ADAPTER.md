# Official Web runtime compatibility

The unmodified official dashboard is served on port 2023. Its same-origin
`/graphql` route passes through the bridge adapter on `127.0.0.1:2025`, then to
unmodified `daed --api-only` on `127.0.0.1:2024`. Neither backend is LAN-bound.
Account and configuration documents are forwarded unchanged. Runtime documents
are parsed and validated with graphql-core against the official schema; aliases,
fragments, variables, directives and operation selection retain GraphQL semantics.
The adapter checks the official user identity before exposing runtime state or
requesting fixed bridge actions. It does not maintain an account database.

`general.dae.running` uses the helper's verified independent process state.
`modified` compares the full normalized GraphQL source plus extensions with the
verified active bundle fingerprint. `version` requires the official binary hash.
`run(dry: true)` requests the existing safe stop; `run(dry: false)` uses existing
preview/validation/apply/start and receipt checks. It never calls official daed's
internal run resolver. Invalid or expired receipts still refuse application.
Run/Stop intentionally affects connectivity; production smoke checks do not stop
a working data plane merely to demonstrate a button.

## Known limitation: Traffic Overview

Official DAE v2.1.1 has in-process `SnapshotRuntimeStats`, but its standalone CLI
has no external interface exposing it. See upstream
`control/runtime_stats.go` at tag `v2.1.1`. TCP relay bytes, cumulative counters,
active TCP relays and the UDP endpoint pool are process-internal semantics.

The read-only collector joins the verified PID's socket file descriptors to
`/proc/PID/net/{tcp,tcp6,udp,udp6}` and checks process start identity. Its
`ownedEstablishedTcpSockets` and `ownedUdpSockets` are explicitly **not** the
logical activeConnections/udpSessions metrics. DNS sockets, two relay legs,
multiplexing and sockets disappearing between samples prevent that equivalence.
It adds no BPF programs and reads no process memory. Interface-wide byte counters
would include unrelated traffic and are not substituted.

Until an equivalent source is available, `runtimeOverview` returns the explicit
GraphQL error `UNSUPPORTED_EQUIVALENT_METRICS`, with safe PID-owned observations,
not the API-only core's zero values. uploadRate, downloadRate, uploadTotal,
downloadTotal, activeConnections, udpSessions and 1m/10m/30m/1h histories are **not
supported as equivalent official metrics**. No fake samples are generated.
This is the accepted `KNOWN_LIMITATION_TRAFFIC_OVERVIEW`. It does not waive
acceptance of other configuration and control functions. Official binaries and all pinned static assets remain
unchanged.

The original dashboard may display its own default zero placeholders after this
GraphQL error. Those placeholders are not measured telemetry and do not count as
a passing dashboard check. The bridge does not modify upstream UI behavior.

New official Config/DNS/Group profiles receive deterministic extension records from their API-effective fields. Existing sealed extension records are preserved. Preview and the independent attestor derive the same effective records; the resulting receipt and bundle cover their hashes without modifying the official database.

When Run follows Stop with edited configuration, the bridge validates the new
candidate, resumes the verified active bundle, then applies the new bundle through
the existing helper. A failed apply reports failure and preserves the helper
rollback result; the previous verified configuration may remain running.
