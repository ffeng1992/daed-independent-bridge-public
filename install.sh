#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
if [ "${1:-}" = "--replace-existing" ]; then
    shift
    if [ "${1:-}" != "--legacy-layout-v031" ]; then
        printf '%s\n' 'Historical one-time layout replacement only. Use upgrade.sh --management-only --plan for an ordinary management update.' >&2
        exit 2
    fi
    shift
    exec python3 -B -m scripts.release_replace "$@"
fi
exec python3 -B -m scripts.release_lifecycle install "$@"
