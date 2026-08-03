#!/usr/bin/env bash
# Run on Orange Pi / RK3588 after code is copied to the board.
# Usage:
#   bash scripts/run_on_board.sh          # real drivers, degraded if unplugged
#   bash scripts/run_on_board.sh strict   # fail unless required hardware is ready
#   bash scripts/run_on_board.sh mock     # synthetic development mode
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="/opt/roboparty/lib/python3/vendor-packages:$ROOT/src:/opt/roboparty/lib/python3/dist-packages"
export PYTHONNOUSERSITE=1
export RP_SERVER_CONFIG="$ROOT/config/server.yaml"

MODE="${1:-hw}"
HOST="${RP_HOST:-0.0.0.0}"
PORT="${RP_PORT:-8765}"

if [ "$MODE" = "mock" ]; then
  export RP_MOCK=1
  echo "[board] mock mode on ${HOST}:${PORT}"
  exec python3 -m rp_server \
    --config "$ROOT/config/dev_robot.yaml" \
    --mock --host "$HOST" --port "$PORT" --log-level info
else
  unset RP_MOCK || true
  ROBOT_CFG="${RP_ROBOT_CONFIG:-/opt/roboparty/share/roboto-inference/config/robot/robot.yaml}"
  if [ ! -f "$ROBOT_CFG" ]; then
    echo "[board] ERROR real robot.yaml not found: $ROBOT_CFG" >&2
    echo "[board] Refusing to silently fall back to mock mode." >&2
    exit 1
  fi
  python3 "$ROOT/scripts/hardware_preflight.py" \
    --config "$ROBOT_CFG" \
    --server-config "$ROOT/config/server.yaml"
  echo "[board] hardware mode config=$ROBOT_CFG"
  STRICT_ARGS=()
  if [ "$MODE" = "strict" ]; then
    STRICT_ARGS=(--require-hardware)
  fi
  exec python3 -m rp_server \
    --config "$ROBOT_CFG" \
    "${STRICT_ARGS[@]}" --host "$HOST" --port "$PORT" --log-level info
fi
