# SPDX-License-Identifier: GPL-3.0
"""Boot-time motor initialization must never enable motors (PRD 5.1/T12)."""

from types import SimpleNamespace

import rp_server.drivers.motors as motors_mod


class FakeMotor:
    def __init__(self, motor_id):
        self.motor_id = motor_id
        self.calls = []

    def get_error_id(self):
        self.calls.append("get_error")
        return 0

    def get_motor_pos(self):
        return 0.0

    def get_motor_spd(self):
        return 0.0

    def get_motor_current(self):
        return 0.0

    def get_motor_temperature(self):
        return 25.0

    def get_motor_control_mode(self):
        return 1

    def get_response_count(self):
        return 0

    def init_motor(self):
        self.calls.append("init_motor")
        return 0

    def deinit_motor(self):
        self.calls.append("deinit_motor")

    def clear_motor_error(self):
        self.calls.append("clear_error")

    def write_motor_flash(self):
        return True

    def get_motor_param(self, *args, **kwargs):
        return 0


class FakeFactory:
    def __init__(self):
        self.motors = []

    def __call__(self, **kwargs):
        motor = FakeMotor(kwargs["motor_id"])
        self.motors.append(motor)
        return motor


CONFIG = {
    "motors": {
        "motor_id": [1, 2],
        "motor_interface": ["vcan0"],
        "motor_interface_type": ["canfd"],
        "motor_type": ["LRO"],
        "motor_num": [2],
        "motor_model": [0, 0],
        "motor_zero_offset": [0.0, 0.0],
    }
}


def _driver(monkeypatch):
    factory = FakeFactory()
    fake_py = SimpleNamespace(
        MotorDriver=SimpleNamespace(create_motor=factory),
    )
    monkeypatch.setattr(motors_mod, "motors_py", fake_py)
    monkeypatch.setattr(motors_mod, "HAS_MOTORS", True)
    return motors_mod.MotorDriver(), factory


def test_boot_init_is_read_only(monkeypatch):
    driver, factory = _driver(monkeypatch)

    assert driver.init(CONFIG) is True
    assert driver.ready is True
    assert driver.enabled is False
    for motor in factory.motors:
        assert "init_motor" not in motor.calls

    # Probe-only shutdown must not disable motors that inference may own.
    driver.deinit()
    for motor in factory.motors:
        assert "deinit_motor" not in motor.calls


def test_enable_is_explicit(monkeypatch):
    driver, factory = _driver(monkeypatch)

    assert driver.init(CONFIG) is True
    assert driver.enable() is True
    assert driver.enabled is True
    for motor in factory.motors:
        assert "init_motor" in motor.calls

    driver.disable()
    assert driver.enabled is False
    for motor in factory.motors:
        assert "deinit_motor" in motor.calls
