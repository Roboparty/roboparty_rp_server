# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Make ``rp_server`` and the generated ``roboparty.v1`` bindings importable."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# rp_server package lives in src/
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Generated protobuf bindings import each other as roboparty.v1.*, so their
# directory must be importable (mirrors rp_server.protocol.gen.__init__).
_GEN = os.path.join(_SRC, "rp_server", "protocol", "gen")
if _GEN not in sys.path:
    sys.path.insert(0, _GEN)
