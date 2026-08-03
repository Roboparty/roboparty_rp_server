# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""MCP-style tools wrapping AtHandler / drivers."""

from __future__ import annotations

import json
from typing import Any, Callable, Awaitable


ToolFn = Callable[[dict[str, Any], Any], Awaitable[Any]]


TOOLS_SPEC = [
    {
        "name": "robot_conn",
        "description": "Query robot connection / hardware ready status (AT+CONN?)",
        "inputSchema": {"type": "object", "properties": {}},
        "readonly": True,
    },
    {
        "name": "robot_sysinfo",
        "description": "Query CPU/memory/loadavg (AT+SYSINFO?)",
        "inputSchema": {"type": "object", "properties": {}},
        "readonly": True,
    },
    {
        "name": "robot_errors",
        "description": "Query motor error codes (AT+ERR?)",
        "inputSchema": {"type": "object", "properties": {}},
        "readonly": True,
    },
    {
        "name": "robot_policy_status",
        "description": "Query inference policy status (AT+POLICY?)",
        "inputSchema": {"type": "object", "properties": {}},
        "readonly": True,
    },
    {
        "name": "robot_status",
        "description": "Full snapshot: motors/imu/bms/policy/joy",
        "inputSchema": {"type": "object", "properties": {}},
        "readonly": True,
    },
    {
        "name": "robot_policy_control",
        "description": "Start or stop inference policy (AT+POLICY=<name>,start|stop)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "action": {"type": "string", "enum": ["start", "stop"]},
            },
            "required": ["name", "action"],
        },
        "readonly": False,
    },
    {
        "name": "robot_button",
        "description": "Inject virtual gamepad button (AT+BTN)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "state": {"type": "string", "enum": ["up", "down"]},
                "id": {"type": "string", "default": "1"},
            },
            "required": ["name", "state"],
        },
        "readonly": False,
    },
]


async def call_tool(name: str, args: dict[str, Any], rp) -> Any:
    from ..protocol.at_parser import AtCommand, CmdType

    handler = rp.at_handler
    if name == "robot_conn":
        cmd = AtCommand(raw="AT+CONN?", cmd=CmdType.CONN_QUERY)
        return await handler.dispatch(cmd)
    if name == "robot_sysinfo":
        cmd = AtCommand(raw="AT+SYSINFO?", cmd=CmdType.SYSINFO_QUERY)
        return await handler.dispatch(cmd)
    if name == "robot_errors":
        cmd = AtCommand(raw="AT+ERR?", cmd=CmdType.ERR_QUERY)
        return await handler.dispatch(cmd)
    if name == "robot_policy_status":
        cmd = AtCommand(raw="AT+POLICY?", cmd=CmdType.POLICY_QUERY)
        return await handler.dispatch(cmd)
    if name == "robot_status":
        return {
            "hw_ready": rp.motors.ready,
            "policy": rp.policy.name,
            "policy_running": rp.policy.running,
            "joy_device": rp.joy.device_path,
            "motor_errors": rp.motors.get_errors(),
            "battery": rp.telemetry.last_battery if rp.telemetry else rp.bms.read(),
            "imu": rp.telemetry.last_imu if rp.telemetry else rp.imu.read(),
            "mock": rp.mock,
        }
    if name == "robot_policy_control":
        action = args.get("action", "")
        pname = args.get("name", "default")
        cmd = AtCommand(
            raw=f"AT+POLICY={pname},{action}",
            cmd=CmdType.POLICY_CMD,
            args=[pname, action],
        )
        return await handler.dispatch(cmd)
    if name == "robot_button":
        bname = args.get("name", "a")
        state = args.get("state", "down")
        cid = str(args.get("id", "1"))
        cmd = AtCommand(
            raw=f"AT+BTN={bname},{state},{cid}",
            cmd=CmdType.BTN,
            args=[bname, state, cid],
        )
        return await handler.dispatch(cmd)
    raise KeyError(f"unknown tool: {name}")


def tool_is_readonly(name: str) -> bool:
    for t in TOOLS_SPEC:
        if t["name"] == name:
            return bool(t.get("readonly", True))
    return True
