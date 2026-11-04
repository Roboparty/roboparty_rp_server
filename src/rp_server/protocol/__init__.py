# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Protocol layer: generated protobuf bindings + codec + command handler."""

PROTOCOL_VERSION = 2
PROTOCOL_FEATURES = (
    "pair-pin-v2",
    "policy-ready-v2",
    "stop-receipt-v2",
    "control-lock-v2",
)

# Importing the generated package installs its directory on sys.path so the
# bindings can use their absolute `roboparty.v1.*` imports.
from . import gen as _gen  # noqa: F401
