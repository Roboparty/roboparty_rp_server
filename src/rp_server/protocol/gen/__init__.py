# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Generated ``roboparty.v1`` protobuf bindings.

Regenerate with ``scripts/gen_proto.sh`` (requires grpcio-tools; board runtime
is ``python3-protobuf`` 4.21.12 / protoc 21.12).

The generated modules import each other via the absolute package path
``roboparty.v1.*`` (protoc has no package-prefix option), so this directory is
put on ``sys.path`` when ``rp_server.protocol`` is imported. Always import the
bindings as ``from roboparty.v1 import ...`` so the protobuf descriptor pool
sees a single copy of each file.
"""

import os as _os
import sys as _sys

_GEN_DIR = _os.path.dirname(_os.path.abspath(__file__))
if _GEN_DIR not in _sys.path:
    _sys.path.insert(0, _GEN_DIR)
