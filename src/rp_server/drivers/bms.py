# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""pybind → bms_py"""

import logging
from typing import Optional

try:
    import bms_py
    HAS_BMS = True
except ImportError:
    HAS_BMS = False

logger = logging.getLogger("rp_server.bms")


class BMSDriver:
    def __init__(self):
        self._bms = None

    def init(self, config: dict) -> bool:
        if not HAS_BMS:
            return False
        try:
            bc = config.get("bms", {})
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

    def deinit(self):
        self._bms = None

    @property
    def ready(self) -> bool:
        return self._bms is not None

    def read(self) -> Optional[dict]:
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
