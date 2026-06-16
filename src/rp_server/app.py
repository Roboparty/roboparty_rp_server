# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""FastAPI application entry point for RoboParty RP Server."""

import asyncio
import logging
import os
import sys

import psutil
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .at_parser import (
    AtCommand, CmdType,
    resp_conn, resp_btn, resp_sysinfo, resp_policy, resp_err,
)
from .monitors import TelemetryMonitor
from .robot import RobotManager, HAS_MOTORS, HAS_IMU, HAS_BMS, HAS_ROBOT

logger = logging.getLogger("rp_server")


def create_app(config_path: str = "") -> FastAPI:
    """Build and return the FastAPI app, wiring up all components."""
    app = FastAPI(title="RoboParty RP Server", version="1.0.0")

    # --- config ---
    if not config_path:
        config_path = os.environ.get(
            "RP_SERVER_CONFIG",
            "/opt/roboparty/share/roboparty-rp-server/config/robot.yaml",
        )
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # --- robot manager ---
    robot = RobotManager(config)
    telemetry = TelemetryMonitor(robot, config)

    # --- lifespan ---
    @app.on_event("startup")
    async def on_startup():
        robot.init_all()
        await telemetry.start()

    @app.on_event("shutdown")
    async def on_shutdown():
        await telemetry.stop()
        robot.deinit_all()

    # ------------------------------------------------------------------
    # REST endpoints
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health():
        return {"status": "ok", "hw_ready": robot.hardware_ready}

    @app.get("/sysinfo")
    async def sysinfo():
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        return {"cpu": cpu, "mem": mem}

    @app.get("/api/status")
    async def api_status():
        """Full robot status snapshot."""
        errors = robot.get_motor_errors()
        bms = robot.read_bms()
        imu = robot.read_imu()
        return JSONResponse({
            "hw_ready": robot.hardware_ready,
            "policy": robot.policy_name,
            "policy_running": robot.policy_running,
            "motor_errors": errors,
            "battery": bms,
            "imu": imu,
        })

    # ------------------------------------------------------------------
    # WebSocket — AT protocol
    # ------------------------------------------------------------------

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        telemetry.add_client(q)

        async def sender():
            while True:
                msg = await q.get()
                try:
                    await ws.send_text(msg)
                except Exception:
                    break

        send_task = asyncio.create_task(sender())

        try:
            # initial connection response
            await ws.send_text(resp_conn(
                connected=True,
                hardware_ok=robot.hardware_ready,
            ))

            async for raw in ws.iter_text():
                cmd = AtCommand.parse(raw)
                if cmd is None:
                    continue
                try:
                    await _handle_at_command(ws, cmd, robot, config)
                except Exception as exc:
                    logger.warning("AT handler error: %s", exc)
        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()
            telemetry.remove_client(q)

    return app


# ------------------------------------------------------------------
# AT command dispatch
# ------------------------------------------------------------------

async def _handle_at_command(ws: WebSocket, cmd: AtCommand,
                              robot: RobotManager, config: dict):
    if cmd.cmd == CmdType.CONN_QUERY:
        await ws.send_text(resp_conn(True, robot.hardware_ready))

    elif cmd.cmd == CmdType.SYSINFO_QUERY:
        cpu = psutil.cpu_percent(interval=0.05)
        mem = psutil.virtual_memory().percent
        await ws.send_text(resp_sysinfo(cpu, mem))

    elif cmd.cmd == CmdType.BTN:
        name, state, cid = cmd.args[0], cmd.args[1], cmd.args[2]
        logger.info("BTN: name=%s state=%s id=%s", name, state, cid)
        await ws.send_text(resp_btn(cid, "OK"))

    elif cmd.cmd == CmdType.JOY:
        axis, val = cmd.args[0], float(cmd.args[1])
        logger.debug("JOY: axis=%s value=%.4f", axis, val)

    elif cmd.cmd == CmdType.POLICY_QUERY:
        state = "RUNNING" if robot.policy_running else "STOPPED"
        await ws.send_text(resp_policy(robot.policy_name or "none", state))

    elif cmd.cmd == CmdType.POLICY_CMD:
        name, action = cmd.args[0], cmd.args[1]
        if action == "start":
            ok = robot.start_policy(name)
            await ws.send_text(resp_policy(name, "RUNNING" if ok else "FAIL"))
        elif action == "stop":
            robot.stop_policy()
            await ws.send_text(resp_policy(name, "STOPPED"))

    elif cmd.cmd == CmdType.ERR_QUERY:
        errors = robot.get_motor_errors()
        if not errors:
            await ws.send_text("+ERR: none")
        else:
            for e in errors:
                await ws.send_text(resp_err(e["id"], e["code"], e["name"]))


# ------------------------------------------------------------------
# Entry point (python -m rp_server)
# ------------------------------------------------------------------

def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="RoboParty RP Server")
    parser.add_argument("--config", default="", help="path to robot.yaml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    # Override host/port from config if present and not given on CLI
    if args.config:
        config_path = args.config
    else:
        config_path = os.environ.get(
            "RP_SERVER_CONFIG",
            "/opt/roboparty/share/roboparty-rp-server/config/robot.yaml",
        )

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    host = args.host
    port = args.port
    if "server" in cfg:
        host = host or cfg["server"].get("host", "0.0.0.0")
        port = cfg["server"].get("port", port)

    app = create_app(config_path)
    uvicorn.run(app, host=host, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
