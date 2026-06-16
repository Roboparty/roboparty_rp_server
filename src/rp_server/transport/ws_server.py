# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Transport layer — FastAPI + WebSocket + Serial + Bluetooth."""

import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from ..protocol.at_handler import AtHandler
from ..protocol.at_parser import AtCommand, resp_conn
from ..drivers.motors import MotorDriver
from ..drivers.imu import IMUDriver
from ..drivers.bms import BMSDriver
from ..drivers.joy import JoyDriver
from ..drivers.policy import PolicyDriver
from ..monitors import TelemetryMonitor
from .serial_server import SerialATServer
from .bt_server import BTServer

logger = logging.getLogger("rp_server.transport")


def create_app(config: dict) -> FastAPI:
    app = FastAPI(title="RoboParty RP Server", version="1.0.0")

    # --- drivers ---
    motors = MotorDriver()
    imu = IMUDriver()
    bms = BMSDriver()
    joy = JoyDriver()
    policy = PolicyDriver(
        config.get("robot", {}).get("launch_cmd",
                                     "ros2 launch roboparty-inference inference.launch.py"))

    # --- protocol ---
    at_handler = AtHandler(motors, imu, bms, joy, policy)

    # --- monitors ---
    telemetry = TelemetryMonitor(imu, bms, motors, config)

    # --- transports ---
    transports_enabled = config.get("transports", {"ws": True, "serial": False, "bluetooth": False})

    scfg = config.get("serial", {})
    serial_srv = SerialATServer(
        scfg.get("port", "/dev/ttyAMA0"),
        scfg.get("baudrate", 115200),
        at_handler,
    ) if transports_enabled.get("serial") else None

    bcfg = config.get("bluetooth", {})
    bt_srv = BTServer(at_handler, channel=bcfg.get("channel", 1)) \
        if transports_enabled.get("bluetooth") else None

    # --- lifespan ---
    @app.on_event("startup")
    async def on_startup():
        motors.init(config)
        imu.init(config)
        bms.init(config)
        joy.init()
        await telemetry.start()
        if serial_srv: await serial_srv.start()
        if bt_srv: await bt_srv.start()

    @app.on_event("shutdown")
    async def on_shutdown():
        if bt_srv: await bt_srv.stop()
        if serial_srv: await serial_srv.stop()
        await telemetry.stop()
        if policy.running:
            await policy.stop()
        joy.deinit()
        bms.deinit()
        imu.deinit()
        motors.deinit()

    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health():
        return {"status": "ok", "hw_ready": motors.ready}

    @app.get("/sysinfo")
    async def sysinfo():
        import psutil
        return {"cpu": psutil.cpu_percent(interval=0.1), "mem": psutil.virtual_memory().percent}

    @app.get("/api/status")
    async def api_status():
        return JSONResponse({
            "hw_ready": motors.ready,
            "policy": policy.name,
            "policy_running": policy.running,
            "joy_device": joy.device_path,
            "motor_errors": motors.get_errors(),
            "battery": bms.read(),
            "imu": imu.read(),
        })

    # ------------------------------------------------------------------
    # WebSocket
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
            await ws.send_text(resp_conn(True, motors.ready))
            async for raw in ws.iter_text():
                cmd = AtCommand.parse(raw)
                if cmd is None:
                    continue
                try:
                    for resp in await at_handler.dispatch(cmd):
                        await ws.send_text(resp)
                except Exception as exc:
                    logger.warning("AT error: %s", exc)
        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()
            telemetry.remove_client(q)

    return app
