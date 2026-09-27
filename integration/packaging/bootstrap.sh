#!/bin/bash
set -euo pipefail
trap 'systemctl poweroff' EXIT
mv /opt/bridge /opt/release-source
cd /opt/release-source
mkdir -p out/m2-official
cp official/dae official/daed out/m2-official/
# Build-time dependency fetch only. Test traffic never uses the uplink.
python3 - <<'PY'
from pathlib import Path
from scripts.release_prepare import prepare
prepare(Path.cwd())
from scripts.release_lifecycle import packages
packages()
PY
# Disable only the disposable VM's distro auto-started DNS; package uses owned units.
systemctl disable --now dnsdist.service || true
touch /evidence/bootstrap-ready
while test ! -e /evidence/network-detached; do sleep 1; done
python3 -m integration.packaging.acceptance
