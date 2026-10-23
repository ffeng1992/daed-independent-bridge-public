# Package scope and evidence boundaries

VERSION remains 0.3.1. This closeout does not create a tag or Release.

## Delivered management source

Runtime source eab90d969b029c60e95c77b78b51116b1a86394f completed a
management-only production update: 33 program/contract files, followed by
installation identity and authenticated management/native DNS checks.
The existing DAE process, active bundle, runtime configuration, database,
extensions, credentials and current geodata were preserved. No new upstream
component compatibility is implied. Detailed private deployment evidence and
recovery backups are not exported.

The isolated evidence covers inventory generation, supported installed-source
comparison, tamper rejection, program-write failure restoration, a subsequent
successful management update and idempotence. It does not close the complete T2
chain, historical UNKNOWN findings or pinned upstream capability limitations.
An independent pre-existing ingress-mapping resolver failure remains open;
source synchronization does not claim that it was repaired.

## Public source boundary

The public tree is generated only by scripts/export-public.sh from an exact
committed private source. .public-source.json records that sourceCommit,
VERSION, file hashes and modes. Public Git history is independent.

Four internal modules are intentionally excluded from both public export and
release source archives:

- bridge_m4/migrate.py: local-only historical database input conversion.
- bridge_m4/private_inputs.py: private backup identity and integrity handling.
- bridge_m4/migration.py: historical dual-dataplane migration coordination.
- bridge_m4/migration_journal.py: the corresponding fixed-path durable journal.

They are not dependencies of the public Web, controller, helper or standard
installation entrypoints. Their associated private migration tests and evidence
are not public installation evidence. Do not add private backup material to
make public and private file counts equal.

A public source archive is not the full internal maintenance tree. In particular,
a public archive must not be described as validated for upgrading an internal
installation containing those modules. The native-DNS cumulative production
update used the exact full maintenance commit, not a public archive. A plan
created from a different payload is a different plan and must not be substituted.
Normal public installation/lifecycle support is checked by its own workflow;
unit/import checks alone do not prove a fresh Debian lifecycle.

## Repository history

The delivered R6-derived maintenance history and the older private main have
no common ancestor. This synchronization retains that maintenance history on
its own branch; it does not force or replace private main. Reconciling those
histories is separate from proving that the deployed source is available.
