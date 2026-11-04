#!/usr/bin/env bash
# Local development launcher.
#
# Some workstations have fastapi 0.63 (Debian/Ubuntu) but a user-site pydantic 2.x,
# which shadows the system pydantic 1.x and breaks fastapi at import time. This
# launcher uses the system fastapi/pydantic and borrows only google.protobuf from
# the user site when the system interpreter cannot import it on its own.
#
# Usage: scripts/dev_run.sh --mock --port 9000
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${RP_PYTHON:-python3}"

if ! PYTHONNOUSERSITE=1 "$PYTHON" -c 'import google.protobuf' >/dev/null 2>&1; then
    USER_SITE="$("$PYTHON" -c 'import site; print(site.getusersitepackages())')"
    SHIM="${RP_SHIM_DIR:-$ROOT/../../test/tmp/rp-server-shim}"
    mkdir -p "$SHIM/google"
    for module in protobuf _upb; do
        if [ -e "$USER_SITE/google/$module" ]; then
            ln -sfn "$USER_SITE/google/$module" "$SHIM/google/$module"
        fi
    done
    export PYTHONPATH="$SHIM${PYTHONPATH:+:$PYTHONPATH}"
fi

export PYTHONNOUSERSITE=1
export PYTHONPATH="$ROOT/src:$ROOT/src/rp_server/protocol/gen${PYTHONPATH:+:$PYTHONPATH}"

if ! "$PYTHON" -c 'import fastapi, pydantic; assert pydantic.VERSION.startswith("1.")' >/dev/null 2>&1; then
    echo "dev_run: need fastapi + pydantic 1.x; set RP_PYTHON to a compatible interpreter" >&2
    exit 1
fi
if ! "$PYTHON" -c 'import google.protobuf' >/dev/null 2>&1; then
    echo "dev_run: google.protobuf is unavailable; install python3-protobuf or a compatible wheel" >&2
    exit 1
fi

exec "$PYTHON" -m rp_server "$@"
