# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Optional stdio JSON-RPC MCP loop for Cursor / Claude Desktop.

Protocol subset: tools/list + tools/call over stdin/stdout newline JSON.
Start with: python3 -m rp_server.mcp.stdio_server --config ...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from ..__main__ import _load_config
from ..drivers.bms import BMSDriver
from ..drivers.imu import IMUDriver
from ..drivers.joy import JoyDriver
from ..drivers.motors import MotorDriver
from ..drivers.policy import PolicyDriver
from ..monitors import TelemetryMonitor
from ..protocol.at_handler import AtHandler
from ..state import AppState
from .tools import TOOLS_SPEC, call_tool, tool_is_readonly

logger = logging.getLogger("rp_server.mcp.stdio")


def _build_rp(config: dict) -> AppState:
    mock = bool(config.get("server", {}).get("mock")) or True  # stdio default mock-safe
    motors = MotorDriver()
    imu = IMUDriver()
    bms = BMSDriver()
    joy = JoyDriver()
    policy = PolicyDriver(config.get("robot", {}).get(
        "launch_cmd", "ros2 launch roboparty-inference inference.launch.py"))
    if not mock:
        motors.init(config)
        imu.init(config)
        bms.init(config)
        joy.init()
    at_handler = AtHandler(motors, imu, bms, joy, policy)
    telemetry = TelemetryMonitor(imu, bms, motors, config, mock=mock)
    return AppState(
        config=config, motors=motors, imu=imu, bms=bms, joy=joy, policy=policy,
        at_handler=at_handler, telemetry=telemetry, mock=mock,
    )


async def _handle(msg: dict, rp: AppState) -> dict:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    readonly = rp.config.get("mcp", {}).get("readonly", True)

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "roboparty-rp-server", "version": "1.1.0"},
            },
        }
    if method == "tools/list":
        tools = []
        for t in TOOLS_SPEC:
            if readonly and not t.get("readonly", True):
                continue
            tools.append({
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            })
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        if readonly and not tool_is_readonly(name):
            return {
                "jsonrpc": "2.0", "id": mid,
                "error": {"code": -32000, "message": "readonly mode"},
            }
        try:
            result = await call_tool(name, args, rp)
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            return {
                "jsonrpc": "2.0", "id": mid,
                "result": {"content": [{"type": "text", "text": text}]},
            }
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message": str(exc)}}
    if method == "notifications/initialized":
        return {}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}


async def run_stdio(config: dict):
    rp = _build_rp(config)
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = await _handle(msg, rp)
        if resp:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="RP Server MCP stdio")
    parser.add_argument("--config", default="")
    args = parser.parse_args()
    config = _load_config(args.config)
    config.setdefault("server", {})["mock"] = config.get("server", {}).get("mock", True)
    asyncio.run(run_stdio(config))


if __name__ == "__main__":
    main()
