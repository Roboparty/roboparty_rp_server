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
    ROBOT_CONFIG="$INSTALL_ROOT/share/roboparty-inference/config/robot/robot.yaml"
    SERVER_CONFIG="$INSTALL_ROOT/share/roboparty-rp-server/config/server.yaml"
    PYTHONPATH="$INSTALL_ROOT/lib/python3/dist-packages:${PYTHONPATH:-}"
else
    # Development mode
    INSTALL_ROOT="$(dirname "$SCRIPT_DIR")"
    ROBOT_CONFIG="$INSTALL_ROOT/../roboparty_inference/config/robot.yaml"
    SERVER_CONFIG="$INSTALL_ROOT/config/server.yaml"
    PYTHONPATH="$INSTALL_ROOT/src:${PYTHONPATH:-}"
fi

export PYTHONPATH
export RP_ROBOT_CONFIG="$ROBOT_CONFIG"
export RP_SERVER_CONFIG="$SERVER_CONFIG"

echo "=== RoboParty RP Server ==="
echo "  robot:   $ROBOT_CONFIG"
echo "  server:  $SERVER_CONFIG"
echo "  listen:  $HOST:$PORT"
echo "============================"

exec python3 -m rp_server --config "$CONFIG_FILE" --host "$HOST" --port "$PORT" --log-level "$LOG_LEVEL"
