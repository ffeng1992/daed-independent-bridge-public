# Deterministic public export

The maintenance repository is the sole source of truth. No private Git history
is pushed to this public repository. `VERSION` is identical in both trees;
`.public-source.json` identifies the source commit and every exported file hash.
No path, timestamp, credential or deployment data is recorded in that metadata.

From a clean maintenance checkout, export the exact committed main:

```sh
sh scripts/export-public.sh --ref main --output /tmp/bridge-public-export
sh scripts/export-public.sh --verify /tmp/bridge-public-export
```

The output must not already exist. The script reads Git objects, not local files.
`scripts/public-allowlist.json` is an explicit reviewed list; new files are never
implicitly published. Each file must pass the fail-closed privacy checks before
any output is written. Export twice into different empty locations and compare
`.public-source.json` and file bytes/modes to reproduce the same tree.
Review allowlist changes and synthetic fixture credentials before publishing;
automatic scanners are not a universal proof that arbitrary text has no secrets.

After scan and tests, initialize the exported directory as the public Git tree
(or apply its deterministic tree as the next commit in the existing public repo),
then ordinary push to public main. Never force-push private history.
Run the public VM command **from that public checkout**:

```sh
python3 -m unittest tests.packaging.test_lifecycle tests.packaging.test_dns tests.packaging.test_export tests.m4.test_install_transaction tests.m4.test_install_payload tests.m4.test_package -v
# On a Mac with QEMU installed:
python3 -m scripts.packaging_vm --local
```

The VM consumes only `git archive HEAD` from this checkout plus hash-locked public
upstream downloads. It creates a fresh Debian disk, removes its bootstrap uplink,
and tests install/health/reinstall/upgrade/retained uninstall/purge with synthetic
local DNS. No private checkout, production account or database is used.

Release builds: `python3 -m scripts.release_build`. This creates a reproducible
source tarball and SHA256SUMS. It neither uploads attachments nor publishes a
Release. Tagging/publishing is a separate explicit maintainer action. Both repos
use the same version tag; the public provenance identifies the private source SHA.
