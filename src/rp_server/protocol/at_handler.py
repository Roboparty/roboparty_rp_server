# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""AT protocol dispatch — stateless, bridges transport ↔ drivers."""

import asyncio
import logging

import psutil

from .at_parser import AtCommand, CmdType, resp_conn, resp_btn, resp_sysinfo, resp_policy, resp_err

logger = logging.getLogger("rp_server.protocol")


class AtHandler:
    """Dispatches AT commands to the appropriate driver."""

    def __init__(self, motors, imu, bms, joy, policy):
        self.motors = motors
        self.imu = imu
        self.bms = bms
        self.joy = joy
        self.policy = policy

    async def dispatch(self, cmd: AtCommand) -> list[str]:
        """Return a list of response strings to send back."""
        responses: list[str] = []

        if cmd.cmd == CmdType.CONN_QUERY:
            hw = "OK" if self.motors.ready else "FAIL"
            responses.append(resp_conn(True, self.motors.ready))

        elif cmd.cmd == CmdType.SYSINFO_QUERY:
            cpu = psutil.cpu_percent(interval=0.05)
            mem = psutil.virtual_memory().percent
            load = ",".join(f"{x:.2f}" for x in psutil.getloadavg())
            responses.append(resp_sysinfo(cpu, mem, f"load={load}"))

        elif cmd.cmd == CmdType.BTN:
            name, state, cid = cmd.args[0], cmd.args[1], cmd.args[2]
            self.joy.set_button(name, state)
            responses.append(resp_btn(cid, "OK", cmd.ts))

        elif cmd.cmd == CmdType.JOY:
            self.joy.set_axis(cmd.args[0], float(cmd.args[1]))

        elif cmd.cmd == CmdType.POLICY_QUERY:
            state = "RUNNING" if self.policy.running else "STOPPED"
            responses.append(resp_policy(self.policy.name or "none", state))

        elif cmd.cmd == CmdType.POLICY_CMD:
            name, action = cmd.args[0], cmd.args[1]
            if action == "start":
                ok = await self.policy.start(name)
                responses.append(resp_policy(name, "RUNNING" if ok else "FAIL"))
            elif action == "stop":
                await self.policy.stop()
                responses.append(resp_policy(name, "STOPPED"))

        elif cmd.cmd == CmdType.ERR_QUERY:
            errors = self.motors.get_errors()
            if not errors:
                responses.append("+ERR: none")
            else:
                for e in errors:
                    responses.append(resp_err(e["id"], e["code"], e["name"]))

        return responses
