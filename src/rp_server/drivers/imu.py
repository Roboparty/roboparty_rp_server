# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""pybind → imu_py"""

import logging
from typing import Optional

try:
    import imu_py
    HAS_IMU = True
except ImportError:
    HAS_IMU = False

logger = logging.getLogger("rp_server.imu")


class IMUDriver:
    def __init__(self):
        self._imu = None

    def init(self, config: dict) -> bool:
        if not HAS_IMU:
            return False
        try:
            ic = config.get("imu", {})
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

    def deinit(self):
        self._imu = None

    @property
    def ready(self) -> bool:
        return self._imu is not None

    def read(self) -> Optional[dict]:
        if not self._imu:
            return None
        try:
            q = self._imu.get_quat()
            av = self._imu.get_ang_vel()
            la = self._imu.get_lin_acc()
            temp = self._imu.get_temperature()
            return {"quat": list(q), "ang_vel": list(av), "lin_acc": list(la), "temp": float(temp)}
        except Exception:
            return None
