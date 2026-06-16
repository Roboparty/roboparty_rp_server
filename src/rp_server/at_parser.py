# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""AT protocol parser/serializer for RoboParty RP Server.

Client → Server (commands):
  AT+CONN?                          query connection status
  AT+BTN=<name>,<state>,<id>        digital button
  AT+JOY=<axis>,<value>             joystick axis (streaming)
  AT+SYSINFO?                       system resource query
  AT+POLICY?                        policy status query
  AT+POLICY=<name>,<action>         policy start/stop (action: start|stop)
  AT+ERR?                           motor error query

Server → Client (responses):
  +CONN: <type>,<status>            connection status response
  +BTN_RSP=<id>,<status>            button acknowledgment
  +SYSINFO: <cpu%>,<mem%>           system info response
  +POLICY: <name>,<state>           policy status response
  +ERR: <motor_id>,<error>,<name>   motor error response (per motor)

Server → Client (push events, prefixed with @):
  @IMU <w> <x> <y> <z> <gx> <gy> <gz> <ax> <ay> <az> <temp>
  @BAT <V> <A> <SoC> <temp>
  @ERR <motor_id> <code> <name>
"""

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CmdType(Enum):
    CONN_QUERY = "AT+CONN?"
    BTN = "AT+BTN"
    JOY = "AT+JOY"
    SYSINFO_QUERY = "AT+SYSINFO?"
    POLICY_QUERY = "AT+POLICY?"
    POLICY_CMD = "AT+POLICY"
    ERR_QUERY = "AT+ERR?"


@dataclass
class AtCommand:
    raw: str
    cmd: CmdType
    args: list[str] = field(default_factory=list)
    ts: float = 0.0

    @classmethod
    def parse(cls, line: str) -> Optional["AtCommand"]:
        line = line.strip()
        if not line:
            return None
        ts = time.time()

        # AT+CONN?
        if line == "AT+CONN?":
            return cls(raw=line, cmd=CmdType.CONN_QUERY, ts=ts)

        # AT+SYSINFO?
        if line == "AT+SYSINFO?":
            return cls(raw=line, cmd=CmdType.SYSINFO_QUERY, ts=ts)

        # AT+POLICY?
        if line == "AT+POLICY?":
            return cls(raw=line, cmd=CmdType.POLICY_QUERY, ts=ts)

        # AT+ERR?
        if line == "AT+ERR?":
            return cls(raw=line, cmd=CmdType.ERR_QUERY, ts=ts)

        # AT+BTN=<name>,<state>,<id>
        m = re.match(r"AT\+BTN=(\w+),(\w+),(\d+)", line)
        if m:
            return cls(raw=line, cmd=CmdType.BTN, args=[m[1], m[2], m[3]], ts=ts)

        # AT+JOY=<axis>,<value>
        m = re.match(r"AT\+JOY=(\w+),([-.\d]+)", line)
        if m:
            return cls(raw=line, cmd=CmdType.JOY, args=[m[1], m[2]], ts=ts)

        # AT+POLICY=<name>,<action>
        m = re.match(r"AT\+POLICY=(\w+),(\w+)", line)
        if m:
            return cls(raw=line, cmd=CmdType.POLICY_CMD, args=[m[1], m[2]], ts=ts)

        return None


# --- Response serializers ---

def resp_conn(connected: bool, hardware_ok: bool) -> str:
    hw = "OK" if hardware_ok else "FAIL"
    st = "CONNECTED" if connected else "DISCONNECTED"
    return f"+CONN: {hw},{st}"


def resp_btn(cmd_id: str, status: str) -> str:
    return f"+BTN_RSP={cmd_id},{status}"


def resp_sysinfo(cpu: float, mem: float) -> str:
    return f"+SYSINFO: {cpu:.1f},{mem:.1f}"


def resp_policy(name: str, state: str) -> str:
    return f"+POLICY: {name},{state}"


def resp_err(motor_id: int, err_code: int, err_name: str) -> str:
    return f"+ERR: {motor_id},0x{err_code:02X},{err_name}"


# --- Push event serializers ---

def push_imu(w: float, x: float, y: float, z: float,
             gx: float, gy: float, gz: float,
             ax: float, ay: float, az: float,
             temp: float) -> str:
    return f"@IMU {w:.6f} {x:.6f} {y:.6f} {z:.6f} {gx:.4f} {gy:.4f} {gz:.4f} {ax:.4f} {ay:.4f} {az:.4f} {temp:.1f}"


def push_bat(voltage: float, current: float, soc: float, temp: float) -> str:
    return f"@BAT {voltage:.2f} {current:.2f} {soc:.1f} {temp:.1f}"


def push_err(motor_id: int, code: int, name: str) -> str:
    return f"@ERR {motor_id} 0x{code:02X} {name}"
