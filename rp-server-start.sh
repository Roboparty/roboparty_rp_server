#!/bin/bash
# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

# RoboParty RP Server startup script.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect install mode
if [[ "$SCRIPT_DIR" == /opt/roboparty/bin* ]]; then
    # Debian package mode
    INSTALL_ROOT="/opt/roboparty"
    CONFIG_FILE="$INSTALL_ROOT/share/roboparty-rp-server/config/robot.yaml"
    PYTHONPATH="$INSTALL_ROOT/lib/python3/dist-packages:${PYTHONPATH:-}"
else
    # Development mode
    INSTALL_ROOT="$(dirname "$SCRIPT_DIR")"
    CONFIG_FILE="$INSTALL_ROOT/config/robot.yaml"
    PYTHONPATH="$INSTALL_ROOT/src:${PYTHONPATH:-}"
fi

export PYTHONPATH
export RP_SERVER_CONFIG="$CONFIG_FILE"

HOST="${RP_HOST:-0.0.0.0}"
PORT="${RP_PORT:-8765}"
LOG_LEVEL="${RP_LOG_LEVEL:-info}"

echo "=== RoboParty RP Server ==="
echo "  config:  $CONFIG_FILE"
echo "  listen:  $HOST:$PORT"
echo "============================"

exec python3 -m rp_server --config "$CONFIG_FILE" --host "$HOST" --port "$PORT" --log-level "$LOG_LEVEL"
