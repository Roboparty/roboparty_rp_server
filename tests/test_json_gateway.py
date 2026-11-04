# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Legacy JSON <-> Envelope mapping for the app gateway."""

import pytest

from rp_server.protocol.codec import Envelope
from rp_server.transport.json_gateway import (control_envelope, skill_envelope,
                                              telemetry_json)

from roboparty.v1 import commands_pb2


def test_control_mapping():
    env = control_envelope({
        "type": "control", "timestamp": 123, "sequence": 7,
        "left_stick_x": 0.5, "left_stick_y": -0.25,
        "right_stick_x": 0.0, "right_stick_y": 1.0,
        "btn_a": True, "btn_lt": True, "btn_rt": False,
        "dpad_up": True,
    })
    body = env.WhichOneof("body")
    assert body == "control"
    assert env.header.timestamp_ms == 123 and env.header.sequence == 7
    axes = {axis.axis: axis.value for axis in env.control.axes}
    assert axes[commands_pb2.Axis.AXIS_LX] == 0.5
    assert axes[commands_pb2.Axis.AXIS_LY] == -0.25
    assert axes[commands_pb2.Axis.AXIS_RY] == 1.0
    assert axes[commands_pb2.Axis.AXIS_LT] == -1.0
    assert axes[commands_pb2.Axis.AXIS_RT] == 0.0
    buttons = {button.button: button.state for button in env.control.buttons}
    assert buttons[commands_pb2.Button.BUTTON_A] == commands_pb2.ButtonState.BUTTON_STATE_DOWN
    assert buttons[commands_pb2.Button.BUTTON_DU] == commands_pb2.ButtonState.BUTTON_STATE_DOWN


def test_skill_mapping():
    env = skill_envelope({"action_id": "wave", "request_id": "r1", "sequence": 2})
    assert env.WhichOneof("body") == "skill_action"
    assert env.skill_action.action_id == "wave"
    assert env.skill_action.request_id == "r1"


def test_telemetry_mapping():
    env = Envelope()
    env.header.timestamp_ms = 5
    env.battery.voltage = 48.2
    env.battery.current = -1.5
    env.battery.soc = 87.0
    env.battery.temp = 30.0
    assert telemetry_json(env) == {
        "type": "battery", "timestamp": 5, "voltage": 48.2,
        "current": -1.5, "soc": 87.0, "temp": 30.0}

    imu = Envelope()
    imu.header.timestamp_ms = 6
    imu.imu.w = 1.0
    imu.imu.temperature = 25.0
    data = telemetry_json(imu)
    assert data["quat"] == [1.0, 0.0, 0.0, 0.0]
    assert data["temp"] == 25.0

    motors = Envelope()
    motor = motors.motors.motors.add()
    motor.id = 3
    motor.position = 0.5
    data = telemetry_json(motors)
    assert data["type"] == "motors"
    assert data["id"] == [3]
    assert data["position"] == [0.5]


def test_left_touch_stick_mirrors_to_translation_axes():
    env = control_envelope({
        "left_stick_x": 0.4, "left_stick_y": -0.6,
        "right_stick_x": 0.0, "right_stick_y": 0.0,
    })
    axes = {axis.axis: axis.value for axis in env.control.axes}
    assert axes[commands_pb2.Axis.AXIS_RX] == pytest.approx(0.4)
    assert axes[commands_pb2.Axis.AXIS_RY] == pytest.approx(-0.6)


def test_right_stick_takes_priority_over_left():
    env = control_envelope({
        "left_stick_x": 0.4, "left_stick_y": -0.6,
        "right_stick_x": 0.8, "right_stick_y": 0.9,
    })
    axes = {axis.axis: axis.value for axis in env.control.axes}
    assert axes[commands_pb2.Axis.AXIS_RX] == pytest.approx(0.8)
    assert axes[commands_pb2.Axis.AXIS_RY] == pytest.approx(0.9)


def test_analog_triggers_map_to_negative_lt_rt():
    env = control_envelope({"lt": 0.6, "rt": 0.25})
    axes = {axis.axis: axis.value for axis in env.control.axes}
    assert axes[commands_pb2.Axis.AXIS_LT] == pytest.approx(-0.6)
    assert axes[commands_pb2.Axis.AXIS_RT] == pytest.approx(-0.25)

    digital = control_envelope({"lt": 0.0, "btn_lt": True})
    axes = {axis.axis: axis.value for axis in digital.control.axes}
    assert axes[commands_pb2.Axis.AXIS_LT] == -1.0
