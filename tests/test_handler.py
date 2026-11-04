# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""CommandHandler routing tests with fake drivers (no hardware)."""

import asyncio

from roboparty.v1 import commands_pb2, envelope_pb2, responses_pb2

from rp_server.protocol.handler import CommandHandler


class FakeMotors:
    def __init__(self, ready=True, errors=None):
        self._ready = ready
        self._errors = errors or []
        self.cleared = False

    @property
    def ready(self):
        return self._ready

    def get_errors(self):
        return list(self._errors)

    def get_states(self):
        return []

    def clear_errors(self):
        self.cleared = True


class FakeJoy:
    def __init__(self):
        self.buttons = []
        self.axes = []
        self.reset_count = 0

    def set_button(self, name, state):
        self.buttons.append((name, state))

    def set_axis(self, name, value):
        self.axes.append((name, value))

    def reset(self):
        self.reset_count += 1


class FakePolicy:
    def __init__(self, running=False, name="default"):
        self.running = running
        self.name = name
        self.started = []
        self.stopped = 0

    async def start(self, name="default"):
        self.started.append(name)
        self.running = True
        return True

    async def stop(self):
        self.stopped += 1
        self.running = False


def _handler(**kw):
    return CommandHandler(
        motors=kw.get("motors", FakeMotors()),
        imu=None, bms=None,
        joy=kw.get("joy", FakeJoy()),
        policy=kw.get("policy", FakePolicy()),
    )


def _run(handler, env):
    return asyncio.run(handler.handle(env))


def _query(what):
    env = envelope_pb2.Envelope()
    env.query.what = what
    return env


def test_conn_query():
    h = _handler(motors=FakeMotors(ready=True))
    out = _run(h, _query(commands_pb2.Query.WHAT_CONN))
    assert len(out) == 1 and out[0].conn.hardware_ok is True

    h = _handler(motors=FakeMotors(ready=False))
    out = _run(h, _query(commands_pb2.Query.WHAT_CONN))
    assert out[0].conn.hardware_ok is False


def test_err_query():
    motors = FakeMotors(errors=[
        {"id": 1, "code": 0x3, "name": "UNDERVOLTAGE", "type": "LRO"},
        {"id": 5, "code": 0x2, "name": "OVERHEAT", "type": "LRO"},
    ])
    out = _run(_handler(motors=motors), _query(commands_pb2.Query.WHAT_ERRORS))
    assert out[0].WhichOneof("body") == "motor_errors"
    assert [(e.motor_id, e.code) for e in out[0].motor_errors.errors] == [(1, 3), (5, 2)]


def test_err_query_empty():
    out = _run(_handler(motors=FakeMotors()), _query(commands_pb2.Query.WHAT_ERRORS))
    assert list(out[0].motor_errors.errors) == []


def test_button_ack_and_joy():
    joy = FakeJoy()
    env = envelope_pb2.Envelope()
    env.button.button = commands_pb2.Button.BUTTON_A
    env.button.state = commands_pb2.ButtonState.BUTTON_STATE_DOWN
    env.button.id = 9
    out = _run(_handler(joy=joy), env)
    assert out[0].WhichOneof("body") == "button_ack"
    assert out[0].button_ack.id == 9
    assert out[0].button_ack.status == responses_pb2.ResponseStatus.RESPONSE_STATUS_OK
    assert joy.buttons == [("a", "down")]


def test_joystick_and_control():
    joy = FakeJoy()
    env = envelope_pb2.Envelope()
    env.joystick.axis = commands_pb2.Axis.AXIS_LX
    env.joystick.value = 0.5
    assert _run(_handler(joy=joy), env) == []
    assert joy.axes == [("lx", 0.5)]

    joy2 = FakeJoy()
    ctrl = envelope_pb2.Envelope()
    ctrl.control.axes.add(axis=commands_pb2.Axis.AXIS_RY, value=-1.0)
    ctrl.control.buttons.add(button=commands_pb2.Button.BUTTON_B,
                             state=commands_pb2.ButtonState.BUTTON_STATE_DOWN)
    assert _run(_handler(joy=joy2), ctrl) == []
    assert joy2.axes == [("ry", -1.0)]
    assert joy2.buttons == [("b", "down")]


def test_joystick_deadzone_and_clamp():
    joy = FakeJoy()
    h = _handler(joy=joy)

    def send(value):
        env = envelope_pb2.Envelope()
        env.joystick.axis = commands_pb2.Axis.AXIS_LX
        env.joystick.value = value
        _run(h, env)

    send(0.005)   # inside dead zone → 0
    send(-0.009)  # inside dead zone → 0
    send(0.5)     # passes through
    send(2.0)     # clamped
    send(-2.0)    # clamped
    assert joy.axes == [("lx", 0.0), ("lx", 0.0), ("lx", 0.5), ("lx", 1.0), ("lx", -1.0)]


def test_policy_query_start_stop():
    policy = FakePolicy(running=True, name="default")
    out = _run(_handler(policy=policy), _query(commands_pb2.Query.WHAT_POLICY))
    assert out[0].policy_response.state == responses_pb2.PolicyResponse.STATE_RUNNING
    assert out[0].policy_response.name == "default"

    policy = FakePolicy(running=False, name="")
    out = _run(_handler(policy=policy), _query(commands_pb2.Query.WHAT_POLICY))
    assert out[0].policy_response.name == "none"

    policy = FakePolicy(running=False)
    env = envelope_pb2.Envelope()
    env.policy_command.name = "default"
    env.policy_command.action = commands_pb2.PolicyCommand.ACTION_START
    out = _run(_handler(policy=policy), env)
    assert out[0].policy_response.state == responses_pb2.PolicyResponse.STATE_RUNNING
    assert policy.started == ["default"]


def test_reset():
    joy, motors = FakeJoy(), FakeMotors()
    policy = FakePolicy(running=True)
    reset = envelope_pb2.Envelope()
    reset.reset.SetInParent()
    out = _run(_handler(motors=motors, joy=joy, policy=policy), reset)
    assert out[0].reset_response.status == responses_pb2.ResponseStatus.RESPONSE_STATUS_OK
    assert joy.reset_count == 1 and motors.cleared and policy.stopped == 1


def test_unknown_body_returns_error():
    out = _run(_handler(), envelope_pb2.Envelope())
    assert out[0].WhichOneof("body") == "error"


def test_err_query_prefers_tui_provider():
    async def provider():
        return [{"id": 3, "code": 7, "name": "TUI_ERR", "type": "LRO"}]

    handler = CommandHandler(
        motors=FakeMotors(errors=[{"id": 1, "code": 1, "name": "DIRECT", "type": "LRO"}]),
        imu=None, bms=None, joy=FakeJoy(), policy=FakePolicy(),
        motor_errors=provider,
    )
    out = _run(handler, _query(commands_pb2.Query.WHAT_ERRORS))
    assert [(e.motor_id, e.code, e.name) for e in out[0].motor_errors.errors] == [
        (3, 7, "TUI_ERR")]


class StopFailurePolicy(FakePolicy):
    async def stop(self):
        self.stopped += 1
        self.running = False
        return False


class FailedPolicy(FakePolicy):
    def __init__(self):
        super().__init__(running=False, name="")
        self.state = "FAIL"


def test_policy_stop_failure_returns_fail():
    policy = StopFailurePolicy(running=True)
    env = envelope_pb2.Envelope()
    env.policy_command.name = "default"
    env.policy_command.action = commands_pb2.PolicyCommand.ACTION_STOP
    out = _run(_handler(policy=policy), env)
    assert out[0].policy_response.state == responses_pb2.PolicyResponse.STATE_FAIL


def test_policy_query_uses_driver_state():
    out = _run(_handler(policy=FailedPolicy()), _query(commands_pb2.Query.WHAT_POLICY))
    assert out[0].policy_response.state == responses_pb2.PolicyResponse.STATE_FAIL
    assert out[0].policy_response.name == "none"


def test_conn_query_advertises_v2():
    h = _handler(motors=FakeMotors(ready=True))
    out = _run(h, _query(commands_pb2.Query.WHAT_CONN))
    assert out[0].conn.protocol_version == 2
    assert "pair-pin-v2" in out[0].conn.features
