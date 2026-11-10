# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Mock hardware backend: driver surface and create_app wiring."""

import asyncio

from fastapi.testclient import TestClient

from roboparty.v1 import commands_pb2, envelope_pb2

from rp_server.drivers.base import (
    BmsDriverLike,
    ImuDriverLike,
    JoyDriverLike,
    MotorsDriver,
    PolicyDriverLike,
)
from rp_server.drivers.mock import (
    MockBmsDriver,
    MockImuDriver,
    MockJoyDriver,
    MockMotorsDriver,
    MockPolicyDriver,
)
from rp_server.transport.ws_server import create_app
from rp_server.monitors.battery import BatterySource


def test_mock_drivers_satisfy_protocols():
    motors = MockMotorsDriver()
    imu = MockImuDriver()
    bms = MockBmsDriver()
    joy = MockJoyDriver()
    policy = MockPolicyDriver()
    assert isinstance(motors, MotorsDriver)
    assert isinstance(imu, ImuDriverLike)
    assert isinstance(bms, BmsDriverLike)
    assert isinstance(joy, JoyDriverLike)
    assert isinstance(policy, PolicyDriverLike)


def test_motors_enable_control_and_errors():
    motors = MockMotorsDriver()
    assert motors.init({"motors": {"motor_id": [1, 2]}})
    assert motors.ready is True
    assert motors.enabled is False

    assert motors.set_mit(0, 1.0, 0.0, 10.0, 1.0, 0.0) is None
    assert motors.get_states()[0]["position"] == 0.0

    assert motors.enable() is True
    motors.set_mit(0, 1.0, 0.0, 10.0, 1.0, 0.0)
    states = motors.get_states()
    assert states[0]["position"] == 1.0
    assert states[0]["mode"] == 1
    assert states[0]["response_count"] == 1

    motors.disable()
    assert motors.enabled is False


def test_motor_error_injection_and_clear():
    motors = MockMotorsDriver()
    motors.init({
        "motors": {"motor_id": [7]},
        "mock": {"motor_errors": [
            {"id": 7, "code": 3, "name": "UNDER_VOLTAGE"},
        ]},
    })
    assert motors.get_errors() == [
        {"id": 7, "code": 3, "name": "UNDER_VOLTAGE", "type": "DM"},
    ]
    motors.clear_errors()
    assert motors.get_errors() == []


def test_sensor_reads_and_joy_recording():
    imu = MockImuDriver()
    bms = MockBmsDriver()
    joy = MockJoyDriver()
    assert imu.read() is None and bms.read() is None
    assert imu.init({}) and bms.init({}) and joy.init()

    assert len(imu.read()["quat"]) == 4
    assert bms.read()["voltage"] > 0
    assert joy.device_path.startswith("mock://")

    joy.set_axis("lx", 0.5)
    joy.set_axis("ly", -2.0)
    joy.set_button("a", "down")
    assert joy.axes == {"lx": 0.5, "ly": -1.0}
    assert joy.buttons == {"a": "down"}
    joy.reset()
    assert joy.axes == {} and joy.buttons == {}


def test_battery_sample_matches_telemetry_schema():
    bms = MockBmsDriver()
    bms.init({})
    message = BatterySource(bms)._message(bms.read())
    assert message.WhichOneof("body") == "battery"
    assert message.battery.soc == 87.0
    assert message.battery.state == "2"
    assert message.battery.power_on is True


def test_mock_policy_never_spawns_process():
    policy = MockPolicyDriver()
    assert asyncio.run(policy.start("default")) is True
    assert policy.running and policy.state == "RUNNING"
    assert asyncio.run(policy.stop()) is True
    assert not policy.running and policy.state == "STOPPED"


def test_create_app_uses_mock_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("RP_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("RP_DEVICE_KEY", raising=False)
    app = create_app({
        "server": {"mock": True},
        "transports": {},
        "tui": {"enabled": False},
        "motors": {"motor_id": [1, 2]},
        "mock": {"motor_errors": [{"id": 2, "code": 2, "name": "OVER_TEMP"}]},
        "identity": {"device_key": str(tmp_path / "key"),
                     "apps_path": str(tmp_path / "apps.json")},
    })
    with TestClient(app):
        rp = app.state.rp
        assert rp.mock is True
        assert rp.motors.ready is True
        assert rp.motors.enabled is False
        assert rp.joy.device_path.startswith("mock://")
        assert rp.policy.name == "none"

        env = envelope_pb2.Envelope()
        env.query.what = commands_pb2.Query.WHAT_CONN
        response = asyncio.run(rp.handler.handle(env))
        assert response[0].conn.hardware_ok is True

        env = envelope_pb2.Envelope()
        env.query.what = commands_pb2.Query.WHAT_ERRORS
        response = asyncio.run(rp.handler.handle(env))
        errors = response[0].motor_errors.errors
        assert [(e.motor_id, e.code) for e in errors] == [(2, 2)]
