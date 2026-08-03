# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Bluetooth WiFi provisioning service.

Listens on an RFCOMM (SPP) socket. A phone pairs with the board, connects,
and sends one JSON line:

    {"ssid": "MyWifi", "password": "secret"}

The service configures WiFi via nmcli and replies with a JSON line:

    {"ok": true, "ssid": "MyWifi", "ip": "10.43.18.63"}
    {"ok": false, "error": "..."}

Run: python3 -m rp_server.btwifi [--channel N]
"""

import argparse
import json
import logging
import socket
import subprocess

logger = logging.getLogger("rp_server.btwifi")

RFCOMM_CHANNEL = 3


def _sh(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def setup_adapter():
    """Make the adapter powered, discoverable and pairable."""
    script = "power on\ndiscoverable on\npairable on\nagent NoInputNoOutput\ndefault-agent\n"
    try:
        subprocess.run(["bluetoothctl"], input=script, capture_output=True,
                       text=True, timeout=15)
        _sh(["sdptool", "add", "--channel", str(RFCOMM_CHANNEL), "SP"])
        logger.info("bluetooth adapter ready (SPP channel %d)", RFCOMM_CHANNEL)
    except Exception as exc:
        logger.warning("adapter setup: %s", exc)


def connect_wifi(ssid: str, password: str) -> dict:
    if not ssid:
        return {"ok": False, "error": "ssid required"}
    _sh(["nmcli", "device", "wifi", "rescan"], timeout=15)
    if password:
        r = _sh(["nmcli", "device", "wifi", "connect", ssid, "password", password], timeout=60)
    else:
        r = _sh(["nmcli", "device", "wifi", "connect", ssid], timeout=60)
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout).strip()[:200]}
    ip = ""
    ri = _sh(["nmcli", "-g", "IP4.ADDRESS", "device", "show"], timeout=10)
    for line in ri.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("127."):
            ip = line.split("/")[0]
            break
    return {"ok": True, "ssid": ssid, "ip": ip}


def handle_client(conn: socket.socket):
    conn.settimeout(60)
    buf = b""
    try:
        while b"\n" not in buf and len(buf) < 4096:
            chunk = conn.recv(1024)
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n")[0].decode("utf-8", errors="replace").strip()
        logger.info("request received (%d bytes)", len(line))
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            conn.send(b'{"ok": false, "error": "invalid json"}\n')
            return
        result = connect_wifi(str(req.get("ssid", "")), str(req.get("password", "")))
        conn.send((json.dumps(result, ensure_ascii=False) + "\n").encode())
        logger.info("result: ok=%s", result.get("ok"))
    except Exception as exc:
        logger.warning("client error: %s", exc)
    finally:
        conn.close()


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Bluetooth WiFi provisioning")
    parser.add_argument("--channel", type=int, default=RFCOMM_CHANNEL)
    args = parser.parse_args()

    setup_adapter()
    srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    srv.bind((socket.BDADDR_ANY, args.channel))
    srv.listen(1)
    logger.info("btwifi listening on RFCOMM channel %d", args.channel)
    while True:
        conn, addr = srv.accept()
        logger.info("client connected: %s", addr)
        handle_client(conn)


if __name__ == "__main__":
    main()
