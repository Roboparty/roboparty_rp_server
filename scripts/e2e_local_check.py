#!/usr/bin/env python3
"""One-shot local check: health / auth / chat / mcp / demo page."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return r.status, r.read()


def post(path: str, data: dict):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def main() -> int:
    print("BASE", BASE)
    st, body = get("/health")
    print("health", st, body.decode()[:200])
    st, body = get("/")
    marker_found = "演示".encode() in body or b"RP Server" in body
    print("demo", st, "bytes", len(body), "ok" if marker_found else "check")
    with urllib.request.urlopen(BASE + "/auth/qr", timeout=5) as r:
        qr = json.loads(r.read().decode())
    cid = qr["challenge"]["challenge_id"]
    print("auth qr", cid[:8])
    post("/auth/scan", {"challenge_id": cid, "user_id": "local_check"})
    with urllib.request.urlopen(BASE + "/auth/poll?challenge_id=" + cid, timeout=5) as r:
        poll = json.loads(r.read().decode())
    print("auth poll", poll.get("status"), "token" in poll)
    chat = post("/chat", {"message": "ping"})[1]
    print("chat", chat.get("session_id", "")[:8], chat.get("mock"))
    with urllib.request.urlopen(BASE + "/mcp/tools", timeout=5) as r:
        tools = json.loads(r.read().decode())
    print("mcp tools", len(tools.get("tools", [])))
    print("ALL_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as e:
        print("FAIL server not up?", e)
        raise SystemExit(1)
