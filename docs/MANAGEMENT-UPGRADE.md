# Verified management-only upgrades

Run `sudo sh upgrade.sh --management-only --plan` from a frozen source release.
The output includes the final payload inventory (SHA-256, root ownership,
permissions, Python/module dependencies), its digest and the calculated
add/modify/delete plan. Save the `plan` object in a root-owned private file;
execute `sudo sh upgrade.sh --management-only --apply-plan /root/plan.json
--expected-plan-sha256 DIGEST` using that same source release.

The installed root-owned install.json, verified against actual bytes,
permissions and ownership, is the old installation authority. There are no
old-release per-file hash exceptions. The reviewed plan binds that manifest
and every new management payload and installer file. Any drift refuses before
stopping services. Supported scope: install schema 1, unchanged upstream lock,
existing Bridge core entrypoints and the sealed extension formats 1/2 (read through the candidate store and trusted contracts before writing). This path
neither downloads dependencies nor upgrades official components or units.

A declared deployment profile is honored. An older native-DNS installation
without layout.json is accepted only after proving the verified DAE PID owns
both TCP/UDP LAN53 and the previous DNS services/timers are retired. The
transaction writes an explicit native ownership record for future lifecycle
operations; it never generates DNS settings or starts retired services.
Neither release.json nor legacy DNS listeners are required. Without a health
query setting the read-only health query uses www.baidu.com.

Only the calculated Bridge modules/contracts and three installed management
scripts change; official binaries, units, vendor dependencies, DAT, credentials,
DB, extensions, activeBundle and DNS files remain in place. Existing required
management services are temporarily stopped and their original states restored.
The DAE and official API are not restarted. Existing release/apply/install locks
and transaction/maintenance guards remain enforced.

Before the first program write, the durable install transaction saves the old
program bytes and manifest and verifies those backup hashes; a verified SQLite
backup is retained alongside them as evidence, never automatically restored by
this program-only update. Failure quiesces management processes, restores those
programs/manifest/layout and their original service states, verifies DAE,
management, source and DB identity. Recovery failure retains the transaction
and returns MANAGEMENT_ROLLBACK_INCOMPLETE; it does not overwrite business data.
Normal use must retain the backup generation until post-update acceptance.

Production-only authority streaming hashing has been incorporated into the
shared implementation. Observation caching is opt-in and status-only; mutation
paths still hash current bytes. Current DAT verification remains separate from
inactive packaged asset verification. The deployed app.js fixes were already
included by the cumulative candidate; its later fixes are retained.
