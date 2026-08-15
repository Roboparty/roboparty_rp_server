# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 changchuanyong (https://github.com/changchuanyong)

"""pybind → head_motor_py (two-axis head controller)."""

import logging

try:
    import head_motor_py
    HAS_HEAD = True
except ImportError:
    HAS_HEAD = False

logger = logging.getLogger("rp_server.head")

# Software limits per axis (deg), matching HeadController defaults.
# Axis 1 = yaw (CCW positive), axis 2 = pitch (up positive).
_AXIS_LIMITS: dict[int, tuple[float, float]] = {
    1: (-120.0, 120.0),
    2: (-20.0, 39.0),
}


class HeadDriver:
    """Wrap head_motor_py.HeadController; UDP angles are relative deltas.

    head_motor_py.move() takes absolute target angles, so this driver
    accumulates each relative delta into a per-axis target and clamps
    it to the software limits before commanding.
    """

    def __init__(self):
        self._ctrl = None
        self._target: dict[int, float] = {1: 0.0, 2: 0.0}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self, config: dict) -> bool:
        if not HAS_HEAD:
            logger.error("head_motor_py is not installed")
            return False
        try:
            hcfg = config.get("head", {})
            can_interface = hcfg.get("can_interface", "can0")
            yaw_id = int(hcfg.get("motor1_id", 1))
            pitch_id = int(hcfg.get("motor2_id", 2))
            self._ctrl = head_motor_py.HeadController(can_interface, yaw_id, pitch_id)
            self._ctrl.init_motors()
            # 用实机当前位置初始化内部目标，首条相对增量指令从当前位置开始
            self._target = {
                1: self._ctrl.get_joint_deg(1),
                2: self._ctrl.get_joint_deg(2),
            }
            logger.info("head motors initialised: can=%s yaw_id=%d pitch_id=%d "
                        "initial yaw=%.2f pitch=%.2f",
                        can_interface, yaw_id, pitch_id,
                        self._target[1], self._target[2])
            return True
        except Exception as exc:
            logger.error("head motor init failed: %s", exc)
            self._ctrl = None
            return False

    def deinit(self):
        if self._ctrl is not None:
            try:
                self._ctrl.deinit_motors()
            except Exception:
                pass
            self._ctrl = None

    @property
    def ready(self) -> bool:
        return self._ctrl is not None

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def move_relative(self, axis: int, delta_deg: float) -> None:
        """Apply a relative angle delta (deg) to one axis.

        Args:
            axis: 1 = yaw, 2 = pitch
            delta_deg: relative increment, CCW positive; clamped so the
                accumulated target stays within the software limits
        """
        if not self.ready:
            logger.warning("head motor driver not ready, ignoring move")
            return
        limits = _AXIS_LIMITS.get(axis)
        if limits is None:
            logger.warning("head move: invalid axis %d", axis)
            return
        lo, hi = limits
        target = max(lo, min(hi, self._target[axis] + delta_deg))
        self._target[axis] = target
        try:
            self._ctrl.move(axis, target)
        except Exception as exc:
            logger.warning("head move[%d] failed: %s", axis, exc)
