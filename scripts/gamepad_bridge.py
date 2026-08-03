#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0
"""Run gamepad → AT bridge.

Examples:
  # Simulated A-button press (bring-up)
  python3 scripts/gamepad_bridge.py --mode sim --ws ws://127.0.0.1:8765/ws

  # Linux HID / G12 as evdev
  python3 scripts/gamepad_bridge.py --mode evdev --device /dev/input/eventX

  # DJI / G12 proprietary SDK stubs (raise until wired)
  python3 scripts/gamepad_bridge.py --mode dji
  python3 scripts/gamepad_bridge.py --mode g12
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rp_server.gamepad import (  # noqa: E402
    AtWsSink,
    DjiSdkSource,
    EvdevSource,
    G12SdkSource,
    SimulatedSource,
    run_bridge,
)


async def main_async(args) -> None:
    sink = AtWsSink(args.ws)
    if args.mode == "sim":
        source = SimulatedSource(vendor=args.vendor)
    elif args.mode == "evdev":
        source = EvdevSource(args.device)
    elif args.mode == "dji":
        source = DjiSdkSource()
    elif args.mode == "g12":
        source = G12SdkSource()
    else:
        raise SystemExit(f"unknown mode {args.mode}")
    await run_bridge(source, sink)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["sim", "evdev", "dji", "g12"], default="sim")
    p.add_argument("--ws", default="ws://127.0.0.1:8765/ws")
    p.add_argument("--device", default="")
    p.add_argument("--vendor", default="dji", choices=["dji", "g12"])
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except NotImplementedError as exc:
        print(f"SDK stub: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"bridge error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
