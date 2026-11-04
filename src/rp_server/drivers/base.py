# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Driver interfaces — the seam between protocol/transport and hardware.

Upper layers (``AtHandler``, telemetry, transports) must depend on these
Protocols, not on the concrete driver modules, so the hardware backend can be
swapped (including a future Rust/FFI implementation) without touching them.

These are structural (duck-typed) interfaces: the existing driver classes in
``drivers/`` already satisfy them, so no runtime change is required to adopt
them. They are intentionally narrow — only what the upper layers actually use.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class RobotDriver(Protocol):
    """Common lifecycle for a hardware driver."""

    @property
    def ready(self) -> bool:
        """True when the device is initialised and usable."""
        ...

    def deinit(self) -> None:
        """Release the device."""
        ...


@runtime_checkable
class MotorsDriver(RobotDriver, Protocol):
    """Motor bus driver (motors_py today)."""

    def init(self, config: dict) -> bool:
        """Initialise from config. Return True on success."""
        ...

    def get_errors(self) -> list[dict]:
        """Cached errors: [{id, code, name, type}, ...]."""
        ...

    def get_states(self) -> list[dict]:
        """Cached states: [{id, position, speed, torque, ...}, ...]."""
        ...

    def clear_errors(self) -> None:
        ...

    def set_mit(self, index: int, pos: float, vel: float,
                kp: float, kd: float, torque: float) -> None:
        ...

    def set_all_mit(self, pos: float, vel: float,
                    kp: float, kd: float, torque: float) -> None:
        ...


@runtime_checkable
class ImuDriverLike(RobotDriver, Protocol):
    def init(self, config: dict) -> bool:
        ...

    def read(self) -> Optional[dict]:
        """{quat, ang_vel, lin_acc, temp} or None."""
        ...


@runtime_checkable
class BmsDriverLike(RobotDriver, Protocol):
    def init(self, config: dict) -> bool:
        ...

    def read(self) -> Optional[dict]:
        """Battery snapshot or None."""
        ...


@runtime_checkable
class JoyDriverLike(RobotDriver, Protocol):
    def init(self) -> bool:
        ...

    @property
    def device_path(self) -> str:
        ...

    def set_button(self, name: str, state: str) -> None:
        ...

    def set_axis(self, name: str, value: float) -> None:
        ...

    def reset(self) -> None:
        ...


@runtime_checkable
class PolicyDriverLike(Protocol):
    """Inference policy process manager (not a hardware device)."""

    @property
    def running(self) -> bool:
        ...

    @property
    def name(self) -> str:
        ...

    async def start(self, name: str = "default") -> bool:
        ...

    async def stop(self) -> None:
        ...
