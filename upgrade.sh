#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
if [ "${1:-}" = "--management-only" ]; then
    shift
    exec python3 -B -m scripts.release_management_upgrade "$@"
fi
exec python3 -B -m scripts.release_lifecycle upgrade "$@"
