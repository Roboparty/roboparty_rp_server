# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Transport layer — FastAPI + WebSocket + Serial + Bluetooth + REST modules."""

import asyncio
import logging
import os

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..protocol.at_handler import AtHandler
from ..protocol.at_parser import AtCommand, resp_conn
from ..drivers.motors import MotorDriver
from ..drivers.imu import IMUDriver
from ..drivers.bms import BMSDriver
from ..drivers.joy import JoyDriver
from ..drivers.policy import PolicyDriver
from ..monitors import TelemetryMonitor
from ..state import AppState
from ..auth.store import AuthStore
from ..auth.router import router as auth_router
from ..chat.session import ChatStore
from ..chat.router import router as chat_router
from ..mcp.router import router as mcp_router
from .serial_server import SerialATServer
from .bt_server import BTServer
from .udp_listener import UDPJoyListener

_WEB_DIR = Path(__file__).resolve().parents[1] / "web"

logger = logging.getLogger("rp_server.transport")


def _missing_hardware(status: dict[str, bool], required: tuple[str, ...]) -> list[str]:
    return [name for name in required if not status.get(name, False)]


def create_app(config: dict) -> FastAPI:
    app = FastAPI(title="RoboParty RP Server", version="1.1.0")

    mock = bool(config.get("server", {}).get("mock")) or os.environ.get("RP_MOCK", "") in ("1", "true", "TRUE")
    if mock:
        config.setdefault("server", {})["mock"] = True
        logger.warning("running in MOCK mode (synthetic telemetry, no hardware pybind)")

    # --- drivers ---
    motors = MotorDriver()
    imu = IMUDriver()
    bms = BMSDriver()
    joy = JoyDriver()
    policy = PolicyDriver(
        config.get("robot", {}).get("launch_cmd",
                                     "ros2 launch roboparty-inference inference.launch.py"))
    hardware_cfg = config.get("hardware", {})
    required_hardware = tuple(hardware_cfg.get("required", ("motors", "imu", "bms")))
    hardware_status = {
        "motors": mock,
        "imu": mock,
        "bms": mock,
        "joy": mock,
    }

    def hardware_ready() -> bool:
        return not _missing_hardware(hardware_status, required_hardware)

    # --- protocol ---
    at_handler = AtHandler(motors, imu, bms, joy, policy)

    # --- monitors ---
    telemetry = TelemetryMonitor(imu, bms, motors, config, mock=mock)

    # --- auth / chat ---
    acfg = config.get("auth", {})
    auth_store = AuthStore(
        qr_ttl_sec=int(acfg.get("qr_ttl_sec", 120)),
        jwt_secret=os.environ.get("RP_JWT_SECRET") or acfg.get("jwt_secret", ""),
        jwt_ttl_sec=int(acfg.get("jwt_ttl_sec", 86400)),
    ) if acfg.get("enabled", True) else None

    ccfg = config.get("chat", {})
    chat_store = ChatStore(max_history=int(ccfg.get("max_history", 20))) \
        if ccfg.get("enabled", True) else None

    rp = AppState(
        config=config,
        hardware_status=hardware_status,
        required_hardware=required_hardware,
        motors=motors,
        imu=imu,
        bms=bms,
        joy=joy,
        policy=policy,
        at_handler=at_handler,
        telemetry=telemetry,
        auth_store=auth_store,
        chat_store=chat_store,
        mock=mock,
    )
    app.state.rp = rp

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

    ucfg = config.get("udp", {})
    udp_srv = UDPJoyListener(
        at_handler,
        host=ucfg.get("host", "0.0.0.0"),
        port=ucfg.get("port", 9000),
    ) if transports_enabled.get("udp") else None

    # --- lifespan ---
    @app.on_event("startup")
    async def on_startup():
        if not mock:
            hardware_status.update({
                "motors": motors.init(config),
                "imu": imu.init(config),
                "bms": bms.init(config),
                "joy": joy.init(),
            })
            missing = _missing_hardware(hardware_status, required_hardware)
            if missing:
                message = f"required hardware unavailable: {', '.join(missing)}"
                if hardware_cfg.get("fail_startup_if_unavailable", False):
                    logger.critical(message)
                    raise RuntimeError(message)
                logger.error("%s (service remains degraded)", message)
            else:
                logger.info("required hardware ready: %s", ", ".join(required_hardware))
        else:
            logger.info("mock: skipping hardware driver init")
        await telemetry.start()
        if serial_srv:
            await serial_srv.start()
        if bt_srv:
            await bt_srv.start()
        if udp_srv:
            await udp_srv.start()
        logger.info("rp_server ready mock=%s port_cfg=%s", mock, config.get("server", {}))

    @app.on_event("shutdown")
    async def on_shutdown():
        if bt_srv:
            await bt_srv.stop()
        if udp_srv:
            udp_srv.stop()
        if serial_srv:
            await serial_srv.stop()
        await telemetry.stop()
        if policy.running:
            await policy.stop()
        if not mock:
            joy.deinit()
            bms.deinit()
            imu.deinit()
            motors.deinit()

    # ------------------------------------------------------------------
    # REST core + demo UI pages
    # ------------------------------------------------------------------

    if _WEB_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=str(_WEB_DIR)), name="ui")

    def _page(name: str):
        path = _WEB_DIR / name
        if path.is_file():
            return FileResponse(path, media_type="text/html; charset=utf-8")
        return JSONResponse({"error": f"{name} missing"}, status_code=404)

    @app.get("/")
    async def page_home():
        return _page("index.html")

    @app.get("/control")
    async def page_control():
        return _page("control.html")

    @app.get("/chat-ui")
    async def page_chat():
        return _page("chat.html")

    @app.get("/full")
    async def page_full():
        return _page("full.html")

    @app.get("/demo")
    async def page_demo():
        return _page("demo.html")

    @app.get("/health")
    async def health():
        ready = True if mock else hardware_ready()
        return {
            "status": "ok" if ready else "degraded",
            "hw_ready": ready,
            "hardware": dict(hardware_status),
            "required_hardware": list(required_hardware),
            "mock": mock,
            "version": "1.1.0",
        }

    @app.get("/sysinfo")
    async def sysinfo():
        import psutil
        load = []
        try:
            load = list(psutil.getloadavg())
        except (AttributeError, OSError):
            load = [0.0, 0.0, 0.0]
        return {
            "cpu": psutil.cpu_percent(interval=0.1),
            "mem": psutil.virtual_memory().percent,
            "load": load,
        }

    @app.get("/api/status")
    async def api_status():
        return JSONResponse({
            "hw_ready": True if mock else hardware_ready(),
            "hardware": dict(hardware_status),
            "mock": mock,
            "policy": policy.name,
            "policy_running": policy.running,
            "joy_device": joy.device_path,
            "motor_errors": [] if mock else motors.get_errors(),
            "battery": telemetry.last_battery or (None if mock else bms.read()),
            "imu": telemetry.last_imu or (None if mock else imu.read()),
        })

    # Feature routers
    if auth_store is not None:
        app.include_router(auth_router)
    if chat_store is not None:
        app.include_router(chat_router)
    if config.get("mcp", {}).get("enabled", True):
        app.include_router(mcp_router)

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
            await ws.send_text(resp_conn(True, True if mock else hardware_ready()))
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
