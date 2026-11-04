# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Shared helpers for telemetry sources."""

from __future__ import annotations

import time


def now_ms() -> int:
    return time.time_ns() // 1_000_000
