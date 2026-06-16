# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""RobotManager: wraps motors_py, imu_py, bms_py, robot_py."""

import logging
import time
from typing import Optional

from .error_codes import (
    DM_ERROR_NAMES, EVO_ERROR_NAMES, LRO_ERROR_NAMES, XYN_ERROR_NAMES,
)

logger = logging.getLogger("rp_server.robot")

# ImportError is OK — the server can run without hardware for testing.
try:
    import motors_py
    HAS_MOTORS = True
except ImportError:
    HAS_MOTORS = False
    logger.warning("motors_py not available — motor control disabled")

try:
    import imu_py
    HAS_IMU = True
except ImportError:
    HAS_IMU = False
    logger.warning("imu_py not available — IMU disabled")

try:
    import bms_py
    HAS_BMS = True
except ImportError:
    HAS_BMS = False
    logger.warning("bms_py not available — BMS disabled")


class MotorInfo:
    """Per-motor metadata."""
    __slots__ = ("motor", "motor_id", "interface", "motor_type", "index")

    def __init__(self, motor, motor_id: int, interface: str, motor_type: str, index: int):
        self.motor = motor
        self.motor_id = motor_id
        self.interface = interface
        self.motor_type = motor_type
        self.index = index


class RobotManager:
    """Lifecycle manager for all robot hardware.

    Usage:
        mgr = RobotManager(config_dict)
        mgr.init_all()
        # … use motors / imu / bms …
        mgr.deinit_all()
    """

    def __init__(self, config: dict):
        self._config = config
        self._motors: list[MotorInfo] = []
        self._imu = None
        self._bms = None

        self._hw_ready = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init_all(self) -> bool:
        """Initialise all hardware subsystems.  Returns True on success."""
        mot_ok = self._init_motors()
        self._init_imu()
        self._init_bms()
        # robot_py.RobotInterface is NOT initialised here — policy
        # execution runs as a separate ros2 inference_node subprocess.
        # RobotInterface would conflict with it on the same CAN bus.
        self._hw_ready = mot_ok
        return mot_ok

    def deinit_all(self):
        """Safely shut down all hardware."""
        self._stop_policy()
        for mi in self._motors:
            try:
                mi.motor.deinit_motor()
            except Exception:
                pass
        self._motors.clear()
        self._hw_ready = False

    @property
    def hardware_ready(self) -> bool:
        return self._hw_ready

    # ------------------------------------------------------------------
    # Motors
    # ------------------------------------------------------------------

    def _init_motors(self) -> bool:
        if not HAS_MOTORS:
            return False
        self._motors.clear()
        try:
            mc = self._config.get("motors", {})
            ids = mc.get("motor_id", [])
            if not ids:
                logger.warning("no motors configured")
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
                        motor_id=mid,
                        interface_type=iface_type,
                        interface=iface,
                        motor_type=mtype,
                        motor_model=model,
                        master_id_offset=master_off,
                        motor_zero_offset=zero_off,
                    )
                    m.init_motor()
                    self._motors.append(MotorInfo(
                        motor=m, motor_id=mid, interface=iface,
                        motor_type=mtype, index=global_idx,
                    ))
                    motor_idx += 1
                    global_idx += 1

            logger.info("motors initialised: %d motors", len(self._motors))
            return True
        except Exception as exc:
            logger.error("motor init failed: %s", exc)
            return False

    def get_motors(self) -> list[MotorInfo]:
        return list(self._motors)

    def get_motor_errors(self) -> list[dict]:
        """Poll all motors for errors.  Returns list of {id,code,name,type}."""
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

    def clear_motor_errors(self):
        for mi in self._motors:
            try:
                mi.motor.clear_motor_error()
            except Exception:
                pass

    def set_motor_mit(self, motor_index: int, pos: float, vel: float, kp: float, kd: float, torque: float):
        """Send MIT command to a single motor by index (0-based)."""
        if motor_index < 0 or motor_index >= len(self._motors):
            return
        try:
            self._motors[motor_index].motor.set_motor_control_mode(
                motors_py.MotorControlMode.MIT)
            self._motors[motor_index].motor.motor_mit_cmd(pos, vel, kp, kd, torque)
        except Exception as exc:
            logger.warning("motor_mit_cmd[%d] failed: %s", motor_index, exc)

    def set_all_motors_mit(self, pos: float, vel: float, kp: float, kd: float, torque: float):
        """Send MIT command to all motors."""
        for mi in self._motors:
            try:
                mi.motor.set_motor_control_mode(motors_py.MotorControlMode.MIT)
                mi.motor.motor_mit_cmd(pos, vel, kp, kd, torque)
            except Exception as exc:
                logger.warning("motor_mit_cmd[%d] failed: %s", mi.motor_id, exc)

    @staticmethod
    def _error_name(motor_type: str, code: int) -> str:
        tables = {
            "DM": DM_ERROR_NAMES,
            "EVO": EVO_ERROR_NAMES,
            "LRO": LRO_ERROR_NAMES,
            "XYN": XYN_ERROR_NAMES,
        }
        return tables.get(motor_type, {}).get(code, "UNKNOWN")

    # ------------------------------------------------------------------
    # IMU
    # ------------------------------------------------------------------

    def _init_imu(self) -> bool:
        if not HAS_IMU:
            return False
        try:
            ic = self._config.get("imu", {})
            self._imu = imu_py.IMUDriver.create_imu(
                imu_id=ic.get("imu_id", 8),
                interface_type=ic.get("interface_type", "serial"),
                interface=ic.get("interface", "/dev/ttyUSB0"),
                imu_type=ic.get("imu_type", "HIPNUC"),
                baudrate=ic.get("baudrate", 921600),
            )
            logger.info("IMU initialised")
            return True
        except Exception as exc:
            logger.error("IMU init failed: %s", exc)
            return False

    def read_imu(self) -> Optional[dict]:
        """Read one IMU sample.  Returns dict or None."""
        if not self._imu:
            return None
        try:
            q = self._imu.get_quat()
            av = self._imu.get_ang_vel()
            la = self._imu.get_lin_acc()
            temp = self._imu.get_temperature()
            return {
                "quat": list(q), "ang_vel": list(av),
                "lin_acc": list(la), "temp": float(temp),
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # BMS
    # ------------------------------------------------------------------

    def _init_bms(self) -> bool:
        if not HAS_BMS:
            return False
        try:
            bc = self._config.get("bms", {})
            self._bms = bms_py.BmsDriver.create_bms(
                bc.get("bms_type", "TWS"),
                bc.get("socket_path", "/tmp/bms.sock"),
            )
            if not self._bms.is_connected():
                logger.warning("BMS daemon not reachable")
                self._bms = None
                return False
            logger.info("BMS initialised")
            return True
        except Exception as exc:
            logger.error("BMS init failed: %s", exc)
            return False

    def read_bms(self) -> Optional[dict]:
        """Read battery snapshot.  Returns dict or None."""
        if not self._bms:
            return None
        try:
            return {
                "voltage": float(self._bms.get_voltage()),
                "current": float(self._bms.get_current()),
                "soc": float(self._bms.get_percentage()),
                "temp": float(self._bms.get_temperature()),
                "capacity": float(self._bms.get_capacity()),
                "soh": float(self._bms.get_soh()),
                "cycles": int(self._bms.get_cycles()),
                "state": str(self._bms.get_work_state()),
                "protect": int(self._bms.get_protect_status()),
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Joystick
    # ------------------------------------------------------------------

    def set_motor_mit(self, motor_index: int, pos: float, vel: float, kp: float, kd: float, torque: float):
        """Send MIT command to a single motor by index (0-based)."""
        if motor_index < 0 or motor_index >= len(self._motors):
            return
        try:
            self._motors[motor_index].motor.set_motor_control_mode(
                motors_py.MotorControlMode.MIT)
            self._motors[motor_index].motor.motor_mit_cmd(pos, vel, kp, kd, torque)
        except Exception as exc:
            logger.warning("motor_mit_cmd[%d] failed: %s", motor_index, exc)

    def set_all_motors_mit(self, pos: float, vel: float, kp: float, kd: float, torque: float):
        """Send MIT command to all motors."""
        for mi in self._motors:
            try:
                mi.motor.set_motor_control_mode(motors_py.MotorControlMode.MIT)
                mi.motor.motor_mit_cmd(pos, vel, kp, kd, torque)
            except Exception as exc:
                logger.warning("motor_mit_cmd[%d] failed: %s", mi.motor_id, exc)
