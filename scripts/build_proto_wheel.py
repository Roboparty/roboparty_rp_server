#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Build the standalone ``roboparty-proto`` wheel from the generated bindings.

The wheel is attached to the GitHub release so downstream consumers (the MCP
server) can install ``roboparty.v1`` without vendoring a copy of
``src/rp_server/protocol/gen/roboparty``.

The wheel version tracks the protobuf package (``roboparty.v1`` semantics), not
the rp_server package: bump it only for incompatible contract changes so the
``releases/latest/download/roboparty_proto-X.Y.Z-py3-none-any.whl`` URL stays
stable across rp_server releases.

Usage:
    python3 scripts/build_proto_wheel.py [--outdir dist]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "src" / "rp_server" / "protocol" / "gen" / "roboparty"
PROTO_VERSION = "2.0.0"

PYPROJECT = f"""\
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "roboparty-proto"
version = "{PROTO_VERSION}"
description = "RoboParty roboparty.v1 protobuf bindings"
requires-python = ">=3.10"
dependencies = ["protobuf>=4.21,<5"]
license = {{ text = "GPL-3.0" }}
classifiers = [
  "Programming Language :: Python :: 3",
  "Operating System :: OS Independent",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["roboparty", "roboparty.*"]
"""


def build(outdir: Path) -> Path:
    if not (GEN / "v1" / "envelope_pb2.py").is_file():
        raise SystemExit(f"missing generated bindings: {GEN}")
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copytree(
            GEN,
            work / "roboparty",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (work / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        try:
            import build  # noqa: F401  (installed in CI)
            command = [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir.resolve())]
        except ImportError:
            command = [
                sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
                "--no-build-isolation", "--wheel-dir", str(outdir.resolve()),
            ]
        subprocess.run(command, cwd=work, check=True)
    wheels = sorted(outdir.glob(f"roboparty_proto-{PROTO_VERSION}-*.whl"))
    if not wheels:
        raise SystemExit(f"wheel not produced in {outdir}")
    return wheels[-1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default=str(ROOT / "dist"))
    args = parser.parse_args(argv)
    wheel = build(Path(args.outdir))
    print(wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
