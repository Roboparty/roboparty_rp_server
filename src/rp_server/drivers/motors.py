# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""pybind → motors_py"""

import logging
from typing import Optional

from ..error_codes import DM_ERROR_NAMES, EVO_ERROR_NAMES, LRO_ERROR_NAMES, XYN_ERROR_NAMES

try:
    import motors_py
    HAS_MOTORS = True
except ImportError:
    HAS_MOTORS = False

logger = logging.getLogger("rp_server.motors")


class MotorInfo:
    __slots__ = ("motor", "motor_id", "interface", "motor_type", "index")
    def __init__(self, motor, motor_id: int, interface: str, motor_type: str, index: int):
        self.motor = motor
        self.motor_id = motor_id
        self.interface = interface
        self.motor_type = motor_type
        self.index = index


class MotorDriver:
    """Manage all motors via motors_py."""

    def __init__(self):
        self._motors: list[MotorInfo] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self, config: dict) -> bool:
        if not HAS_MOTORS:
            return False
        self._motors.clear()
        try:
            mc = config.get("motors", {})
            ids = mc.get("motor_id", [])
            if not ids:
                return False

            models = mc.get("motor_model", [0] * len(ids))
            offsets = mc.get("motor_zero_offset", [0.0] * len(ids))
            iface_types = mc.get("motor_interface_type", ["can"])
            ifaces = mc.get("motor_interface", ["can0"])
            mtypes = mc.get("motor_type", ["DM"])
            num_per_bus = mc.get("motor_num", [len(ids)])
            master_off = mc.get("master_id_offset", 0)

            motor_idx = 0
            global_idx = 0
            for bus_i, n in enumerate(num_per_bus):
                iface = ifaces[bus_i] if bus_i < len(ifaces) else "can0"
                iface_type = iface_types[bus_i] if bus_i < len(iface_types) else "can"
                mtype = mtypes[bus_i] if bus_i < len(mtypes) else "DM"
                for _ in range(n):
                    if motor_idx >= len(ids):
                        break
                    mid = ids[motor_idx]
                    model = models[motor_idx] if motor_idx < len(models) else 0
                    zero_off = offsets[motor_idx] if motor_idx < len(offsets) else 0.0
                    m = motors_py.MotorDriver.create_motor(
                        motor_id=mid, interface_type=iface_type, interface=iface,
                        motor_type=mtype, motor_model=model,
                        master_id_offset=master_off, motor_zero_offset=zero_off,
                    )
                    m.init_motor()
                    self._motors.append(MotorInfo(
                        motor=m, motor_id=mid, interface=iface,
                        motor_type=mtype, index=global_idx,
                    ))
                    motor_idx += 1
                    global_idx += 1

            logger.info("motors initialised: %d", len(self._motors))
            return True
        except Exception as exc:
            logger.error("motor init failed: %s", exc)
            return False

    def deinit(self):
        for mi in self._motors:
            try:
                mi.motor.deinit_motor()
            except Exception:
                pass
        self._motors.clear()

    @property
    def ready(self) -> bool:
        return len(self._motors) > 0

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------

    def get_errors(self) -> list[dict]:
        errors = []
        for mi in self._motors:
            try:
                code = mi.motor.get_error_id()
            except Exception:
                continue
            if code == 0:
                continue
            name = self._error_name(mi.motor_type, code)
            errors.append({"id": mi.motor_id, "code": int(code), "name": name, "type": mi.motor_type})
        return errors

    def clear_errors(self):
        for mi in self._motors:
            try:
                mi.motor.clear_motor_error()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def set_mit(self, index: int, pos: float, vel: float, kp: float, kd: float, torque: float):
        if index < 0 or index >= len(self._motors):
            return
        try:
            self._motors[index].motor.set_motor_control_mode(motors_py.MotorControlMode.MIT)
            self._motors[index].motor.motor_mit_cmd(pos, vel, kp, kd, torque)
        except Exception as exc:
            logger.warning("motor_mit_cmd[%d] failed: %s", index, exc)

    def set_all_mit(self, pos: float, vel: float, kp: float, kd: float, torque: float):
        for mi in self._motors:
            try:
                mi.motor.set_motor_control_mode(motors_py.MotorControlMode.MIT)
                mi.motor.motor_mit_cmd(pos, vel, kp, kd, torque)
            except Exception as exc:
                logger.warning("motor_mit_cmd[%d] failed: %s", mi.motor_id, exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _error_name(motor_type: str, code: int) -> str:
        tables = {"DM": DM_ERROR_NAMES, "EVO": EVO_ERROR_NAMES, "LRO": LRO_ERROR_NAMES, "XYN": XYN_ERROR_NAMES}
        return tables.get(motor_type, {}).get(code, "UNKNOWN")
