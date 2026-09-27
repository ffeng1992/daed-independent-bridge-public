#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
exec python3 -B -m scripts.release_lifecycle upgrade "$@"
