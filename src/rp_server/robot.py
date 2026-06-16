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

try:
    import robot_py
    HAS_ROBOT = True
except ImportError:
    HAS_ROBOT = False
    logger.warning("robot_py not available — policy execution disabled")


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
        # … use motors / imu / bms / robot_interface …
        mgr.deinit_all()
    """

    def __init__(self, config: dict):
        self._config = config
        self._motors: list[MotorInfo] = []
        self._imu = None
        self._bms = None
        self._robot_iface = None

        self._hw_ready = False
        self._policy_name = ""
        self._policy_running = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init_all(self) -> bool:
        """Initialise all hardware subsystems.  Returns True on success."""
        mot_ok = self._init_motors()
        imu_ok = self._init_imu()
        bms_ok = self._init_bms()
        pol_ok = self._init_robot()
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
            for bus_cfg in self._config.get("motors", []):
                iface = bus_cfg["interface"]
                iface_type = bus_cfg["interface_type"]
                mtype = bus_cfg["motor_type"]
                ids = bus_cfg["motor_ids"]
                models = bus_cfg.get("motor_models", [0] * len(ids))
                offsets = bus_cfg.get("motor_zero_offsets", [0.0] * len(ids))
                master_off = bus_cfg.get("master_id_offset", 0)

                for idx, mid in enumerate(ids):
                    model = models[idx] if idx < len(models) else 0
                    zero_off = offsets[idx] if idx < len(offsets) else 0.0
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
                        motor_type=mtype, index=idx,
                    ))
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
    # Policy / robot_py
    # ------------------------------------------------------------------

    def _init_robot(self) -> bool:
        if not HAS_ROBOT:
            return False
        try:
            cfg_path = self._config.get("robot", {}).get(
                "policy_config",
                "/opt/roboparty/share/roboparty-inference/config/inference/inference.yaml",
            )
            self._robot_iface = robot_py.RobotInterface(cfg_path)
            logger.info("RobotInterface initialised (config: %s)", cfg_path)
            return True
        except Exception as exc:
            logger.error("RobotInterface init failed: %s", exc)
            return False

    def start_policy(self, name: str = "") -> bool:
        if not self._robot_iface:
            return False
        try:
            self._robot_iface.init_motors()
            time.sleep(0.5)
            self._policy_name = name or "default"
            self._policy_running = True
            logger.info("policy started: %s", self._policy_name)
            return True
        except Exception as exc:
            logger.error("start policy failed: %s", exc)
            return False

    def stop_policy(self):
        self._policy_running = False
        self._policy_name = ""
        self._stop_policy()

    def _stop_policy(self):
        if not self._robot_iface:
            return
        try:
            # RobotInterface cleanup — motors are managed by the interface
            pass
        except Exception:
            pass

    @property
    def policy_name(self) -> str:
        return self._policy_name

    @property
    def policy_running(self) -> bool:
        return self._policy_running

    # ------------------------------------------------------------------
    # Joystick action
    # ------------------------------------------------------------------

    def apply_joystick_mit(self, joint_positions: list[float],
                           kp: float = 10.0, kd: float = 1.0):
        """Direct per-joint MIT control (used by joystick)."""
        for i, pos in enumerate(joint_positions):
            self.set_motor_mit(i, float(pos), 0.0, kp, kd, 0.0)
