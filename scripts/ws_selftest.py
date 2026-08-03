#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0
"""WS / REST self-test for rp_server (board or mock).

Usage:
  python3 scripts/ws_selftest.py --url http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request


def http_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode())


async def ws_probe(ws_url: str, timeout: float = 5.0) -> list[str]:
    import websockets

    seen: list[str] = []
    async with websockets.connect(ws_url) as ws:
        hello = await asyncio.wait_for(ws.recv(), timeout=timeout)
        seen.append(str(hello))
        await ws.send("AT+CONN?")
        seen.append(str(await asyncio.wait_for(ws.recv(), timeout=timeout)))
        await ws.send("AT+SYSINFO?")
        seen.append(str(await asyncio.wait_for(ws.recv(), timeout=timeout)))
        # wait briefly for a push frame
        try:
            push = await asyncio.wait_for(ws.recv(), timeout=2.0)
            seen.append(str(push))
        except asyncio.TimeoutError:
            seen.append("(no push within 2s)")
    return seen


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8765")
    args = p.parse_args()
    base = args.url.rstrip("/")
    ws_url = base.replace("http://", "ws://").replace("https://", "wss://") + "/ws"

    print("== GET /health ==")
    health = http_get(f"{base}/health")
    print(health)
    if health.get("status") != "ok":
        print("FAIL health", file=sys.stderr)
        return 1

    print("== GET /api/status ==")
    print(http_get(f"{base}/api/status"))

    print("== WebSocket AT probe ==")
    try:
        lines = asyncio.run(ws_probe(ws_url))
    except Exception as exc:
        print(f"FAIL ws: {exc}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)

    ok = any(x.startswith("+CONN") for x in lines)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
