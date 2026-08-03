# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Shared application state attached to FastAPI app.state."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AppState:
    config: dict = field(default_factory=dict)
    hardware_status: dict[str, bool] = field(default_factory=dict)
    required_hardware: tuple[str, ...] = field(default_factory=tuple)
    motors: Any = None
    imu: Any = None
    bms: Any = None
    joy: Any = None
    policy: Any = None
    at_handler: Any = None
    telemetry: Any = None
    auth_store: Any = None
    chat_store: Any = None
    mock: bool = False
