# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Command handler — dispatches protobuf ``Envelope`` commands to drivers.

Replaces the former AT ``AtHandler``. Auth/session concerns stay in the
transport that owns them (currently UDP); this handler only routes robot
commands and queries.
"""

from __future__ import annotations

import asyncio
import logging
import time

import psutil

from roboparty.v1 import commands_pb2, envelope_pb2, responses_pb2

from . import PROTOCOL_FEATURES, PROTOCOL_VERSION
from .codec import Envelope
from .enums import axis_name, button_name, button_state_name

logger = logging.getLogger("rp_server.protocol")

_RespStatus = responses_pb2.ResponseStatus
_PolicyState = responses_pb2.PolicyResponse.State
_QueryWhat = commands_pb2.Query.What

#: Joystick values within ±DEAD_ZONE are quantized to 0 (release-to-center).
JOYSTICK_DEAD_ZONE = 0.01


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class CommandHandler:
    """Routes a decoded command ``Envelope`` and returns response envelopes."""

    def __init__(self, motors, imu, bms, joy, policy, motor_errors=None):
        self.motors = motors
        self.imu = imu
        self.bms = bms
        self.joy = joy
        self.policy = policy
        # Optional async provider returning read-only motor error dicts
        # (rp_server wires this to the robopi-tui backend).
        self._motor_errors_provider = motor_errors

    async def handle(self, env: Envelope) -> list[Envelope]:
        body = env.WhichOneof("body")
        if body == "query":
            return await self._query(env)
        if body == "button":
            return self._button(env)
        if body == "joystick":
            self._apply_joystick(env.joystick.axis, env.joystick.value)
            return []
        if body == "control":
            self._control(env)
            return []
        if body == "policy_command":
            return await self._policy(env)
        if body == "reset":
            return await self._reset()
        if body == "skill_action":
            action = env.skill_action
            logger.info("技能动作: action=%s request=%s seq=%s",
                        action.action_id, action.request_id, action.sequence)
            return []
        logger.debug("unhandled command body: %s", body)
        return [self._wrap("error", responses_pb2.Error(
            code=1, message=f"unsupported command: {body or '<empty>'}"))]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _query(self, env: Envelope) -> list[Envelope]:
        what = env.query.what
        if what == _QueryWhat.WHAT_CONN:
            return [self._wrap("conn", responses_pb2.ConnResponse(
                connected=True, hardware_ok=self.motors.ready,
                protocol_version=PROTOCOL_VERSION,
                features=list(PROTOCOL_FEATURES)))]

        if what == _QueryWhat.WHAT_SYSINFO:
            cpu = await asyncio.to_thread(psutil.cpu_percent, 0.05)
            mem = psutil.virtual_memory().percent
            info = responses_pb2.SysInfoResponse(cpu_percent=cpu, mem_percent=mem)
            info.load_avg.extend(float(x) for x in psutil.getloadavg())
            return [self._wrap("sysinfo", info)]

        if what == _QueryWhat.WHAT_POLICY:
            return [self._wrap("policy_response",
                               self._policy_response(self.policy.name or "none",
                                                     self._policy_state()))]

        if what == _QueryWhat.WHAT_ERRORS:
            errors = [responses_pb2.MotorError(
                motor_id=int(e.get("id", e.get("motor_id", 0))),
                code=int(e.get("code", 0)),
                name=str(e.get("name", "")),
                type=str(e.get("type", "")),
            ) for e in await self._motor_errors()]
            return [self._wrap("motor_errors", responses_pb2.MotorErrors(errors=errors))]

        return [self._wrap("error", responses_pb2.Error(code=2, message="unknown query"))]

    async def _motor_errors(self) -> list[dict]:
        if self._motor_errors_provider is None:
            return list(self.motors.get_errors())
        try:
            return await self._motor_errors_provider()
        except Exception as exc:
            logger.warning("motor error backend failed, using direct driver: %s", exc)
            return list(self.motors.get_errors())

    def _button(self, env: Envelope) -> list[Envelope]:
        event = env.button
        name = button_name(event.button)
        if name:
            self.joy.set_button(name, button_state_name(event.state))
        return [self._wrap("button_ack", responses_pb2.ButtonAck(
            id=event.id, status=_RespStatus.RESPONSE_STATUS_OK))]

    def _apply_joystick(self, axis: int, value: float):
        name = axis_name(axis)
        if not name:
            return
        v = float(value)
        if -JOYSTICK_DEAD_ZONE < v < JOYSTICK_DEAD_ZONE:
            v = 0.0
        self.joy.set_axis(name, max(-1.0, min(1.0, v)))

    def _control(self, env: Envelope):
        for axis in env.control.axes:
            self._apply_joystick(axis.axis, axis.value)
        for event in env.control.buttons:
            name = button_name(event.button)
            if name:
                self.joy.set_button(name, button_state_name(event.state))

    async def _policy(self, env: Envelope) -> list[Envelope]:
        cmd = env.policy_command
        if cmd.action == commands_pb2.PolicyCommand.ACTION_START:
            ok = await self.policy.start(cmd.name)
            state = _PolicyState.STATE_RUNNING if ok else _PolicyState.STATE_FAIL
        elif cmd.action == commands_pb2.PolicyCommand.ACTION_STOP:
            ok = await self.policy.stop()
            state = _PolicyState.STATE_STOPPED if ok is not False else _PolicyState.STATE_FAIL
        else:
            state = _PolicyState.STATE_UNSPECIFIED
        return [self._wrap("policy_response", self._policy_response(cmd.name, state))]

    def _policy_state(self):
        state = getattr(self.policy, "state", None)
        if state is None:
            return (_PolicyState.STATE_RUNNING if self.policy.running
                    else _PolicyState.STATE_STOPPED)
        return {
            "RUNNING": _PolicyState.STATE_RUNNING,
            "FAIL": _PolicyState.STATE_FAIL,
            "STOPPED": _PolicyState.STATE_STOPPED,
            "STARTING": _PolicyState.STATE_STARTING,
            "STOPPING": _PolicyState.STATE_STOPPING,
        }.get(state, _PolicyState.STATE_UNKNOWN)

    def _policy_response(self, name: str, state) -> responses_pb2.PolicyResponse:
        return responses_pb2.PolicyResponse(
            name=name,
            state=state,
            pid=max(0, int(getattr(self.policy, "pid", 0) or 0)),
            exit_code=int(getattr(self.policy, "exit_code", -1)),
            message=str(getattr(self.policy, "message", "") or ""),
            ready=state == _PolicyState.STATE_RUNNING,
            updated_at_ms=int(getattr(self.policy, "updated_at_ms", _now_ms())),
        )

    async def _reset(self) -> list[Envelope]:
        try:
            self.joy.reset()
            self.motors.clear_errors()
            if self.policy.running:
                await self.policy.stop()
            status = _RespStatus.RESPONSE_STATUS_OK
        except Exception as exc:
            logger.warning("reset failed: %s", exc)
            status = _RespStatus.RESPONSE_STATUS_FAIL
        return [self._wrap("reset_response", responses_pb2.ResetResponse(status=status))]

    # ------------------------------------------------------------------

    @staticmethod
    def _wrap(field: str, message) -> Envelope:
        env = envelope_pb2.Envelope()
        env.header.timestamp_ms = _now_ms()
        getattr(env, field).CopyFrom(message)
        return env
