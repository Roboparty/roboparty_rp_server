# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""Transport layer — FastAPI + WebSocket (protobuf) + Serial + Bluetooth + UDP."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
import secrets
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict

from .. import __version__
from ..auth.app_auth import AuthError, issue_token, verify_app_signature
from ..auth.access import AccessPolicy
from ..auth.device_key import DEFAULT_PATH, identity_fields, load_or_create
from ..auth.pairing import PairingError, PairingManager
from ..auth.tls import cert_spki_sha256
from .json_gateway import control_envelope, skill_envelope, telemetry_json
from ..protocol import PROTOCOL_FEATURES, PROTOCOL_VERSION
from ..protocol.codec import CODEC, Envelope
from ..protocol.handler import CommandHandler
from ..protocol.control_lease import ControlError, ControlLease
from roboparty.v1 import auth_pb2, commands_pb2, responses_pb2
from .tui_backend import TuiBackend, TuiError
from ..drivers.motors import MotorDriver
from ..drivers.imu import IMUDriver
from ..drivers.bms import BMSDriver
from ..drivers.joy import JoyDriver
from ..drivers.policy import DEFAULT_LAUNCH_CMD, PolicyDriver
from ..drivers.ros_probe import service_ready_check
from ..monitors import TelemetryMonitor
from ..state import AppState
from .serial_server import SerialServer
from .bt_server import BTServer
from .udp_listener import UDPJoyListener
from .can_joy_listener import CANJoyListener

logger = logging.getLogger("rp_server.transport")
packet_logger = logging.getLogger("rp_server.packets")


def _missing_hardware(status: dict[str, bool], required: tuple[str, ...]) -> list[str]:
    return [name for name in required if not status.get(name, False)]


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _conn_envelope(connected: bool, hardware_ok: bool) -> Envelope:
    env = Envelope()
    env.header.timestamp_ms = _now_ms()
    env.conn.connected = connected
    env.conn.hardware_ok = hardware_ok
    env.conn.protocol_version = PROTOCOL_VERSION
    env.conn.features.extend(PROTOCOL_FEATURES)
    return env


_TUI_HTTP_STATUS = {
    "DISABLED": 403,
    "PERMISSION_DENIED": 403,
    "UNAVAILABLE": 503,
    "TIMEOUT": 504,
    "BAD_RESPONSE": 502,
    "NOT_FOUND": 404,
    "BUSY": 409,
    "REQUEST_CONFLICT": 409,
    "INTERRUPTED_JOB": 409,
    "UNSUPPORTED_TASK": 400,
    "INVALID_PARAMS": 400,
    "PARSE_ERROR": 400,
}


def _tui_error_response(exc: TuiError) -> JSONResponse:
    status = _TUI_HTTP_STATUS.get(exc.code, 500)
    return JSONResponse(
        {"error": {"code": exc.code, "message": str(exc)}},
        status_code=status,
    )


def create_app(config: dict) -> FastAPI:
    app = FastAPI(title="RoboParty RP Server", version=__version__)

    # These old paths write directly to drivers and cannot participate in leases.
    transports = config.get("transports", {})
    unsupported = [name for name in ("udp", "serial", "bluetooth") if transports.get(name)]
    if config.get("can_gamepad", {}).get("enabled"):
        unsupported.append("can_gamepad")
    if unsupported:
        raise ValueError("Unleased control transports must be disabled: " + ", ".join(unsupported))

    mock = bool(config.get("server", {}).get("mock")) or os.environ.get("RP_MOCK", "") in ("1", "true", "TRUE")
    if mock:
        config.setdefault("server", {})["mock"] = True
        logger.warning("running in MOCK mode (synthetic telemetry, no hardware pybind)",
                       extra={"event_type": "startup"})

    # --- drivers ---
    motors = MotorDriver()
    imu = IMUDriver()
    bms = BMSDriver()
    joy = JoyDriver()
    robot_cfg = config.get("robot", {})
    ready_service = str(robot_cfg.get("ready_service", "start_inference"))
    ready_timeout_s = float(robot_cfg.get("ready_timeout_s", 15.0))
    control_lock = robot_cfg.get("control_lock", "/dev/shm/roboparty-control.lock")
    policy = PolicyDriver(
        robot_cfg.get("launch_cmd", DEFAULT_LAUNCH_CMD),
        ready_check=service_ready_check(ready_service),
        ready_timeout_s=ready_timeout_s,
        lock_path=control_lock,
        log_path=os.path.join(config.get("logging", {}).get("dir", "logs"), "policy.log"),
    )
    hardware_cfg = config.get("hardware", {})
    required_hardware = tuple(hardware_cfg.get("required", ("motors", "imu")))
    hardware_status = {
        "motors": mock,
        "imu": mock,
        "bms": mock,
        "joy": mock,
    }

    def hardware_ready() -> bool:
        return not _missing_hardware(hardware_status, required_hardware)

    # --- board-management backend (robopi-tui JSON-RPC) ---
    tui_cfg = config.get("tui", {})
    tui = TuiBackend(tui_cfg)
    identity_cfg = config.get("identity", {})
    device_identity = identity_fields(identity_cfg)
    pairing = PairingManager(identity_cfg.get("apps_path") or "/etc/rp-server/auth/apps.json")
    app.state.pairing = pairing
    try:
        jwt_key = load_or_create(Path(identity_cfg.get("device_key") or os.environ.get("RP_DEVICE_KEY") or DEFAULT_PATH))
    except Exception as exc:
        logger.warning("JWT signing key unavailable: %s", exc)
        jwt_key = None
    access = AccessPolicy(jwt_key, pairing, os.environ.get("RP_SERVICE_TOKEN", ""),
                          config.get("auth", {}).get("service_scopes", ["read", "control", "admin"]))

    @app.middleware("http")
    async def authorize_http(request: Request, call_next):
        path = request.url.path
        # Pairing retains its one-time code/local-operator checks below.
        public = {"/health", "/identity", "/pair/code", "/pair/register",
                  "/pair/apps", "/pair/revoke"}
        if path not in public:
            required = "read" if request.method in ("GET", "HEAD") else "admin"
            try:
                access.verify(access.bearer(request.headers.get("authorization")), required)
            except AuthError as exc:
                return JSONResponse({"error": {"code": exc.code, "message": str(exc)}},
                                    status_code=403 if exc.code == "FORBIDDEN" else 401)
        return await call_next(request)
    tls_cfg = config.get("tls", {})
    tls_spki = cert_spki_sha256(tls_cfg.get("certfile") or "")
    pair_attempts: dict[str, list] = {}
    motor_cache_s = float(tui_cfg.get("motor_cache_s", 2.0))
    identity_cache_s = float(tui_cfg.get("identity_cache_s", 60.0))
    motor_cache = {"at": 0.0, "rows": []}
    identity_cache = {"at": 0.0, "data": {}}

    async def motor_errors_provider() -> list[dict]:
        """Read-only motor errors from TUI; fall back to the direct driver."""
        now = time.monotonic()
        if now - motor_cache["at"] < motor_cache_s:
            return list(motor_cache["rows"])
        if mock:
            rows = []
        elif tui.enabled and tui.available:
            try:
                data = await tui.motor_errors()
            except Exception as exc:
                logger.warning("TUI motor query failed, using direct driver: %s", exc)
                rows = list(motors.get_errors())
            else:
                rows = []
                for motor in data.get("motors", []):
                    code = int(motor.get("error") or 0)
                    if not motor.get("feedback"):
                        rows.append({"id": motor.get("id", 0), "code": 0,
                                     "name": "NO_FEEDBACK",
                                     "type": motor.get("type", "")})
                    elif code:
                        rows.append({"id": motor.get("id", 0), "code": code,
                                     "name": motor.get("errorName", ""),
                                     "type": motor.get("type", "")})
        else:
            rows = list(motors.get_errors())
        motor_cache.update(at=now, rows=rows)
        return list(rows)

    async def board_identity() -> dict:
        """Public robot identity; SN/model come from TUI, never from rp_server."""
        now = time.monotonic()
        if now - identity_cache["at"] < identity_cache_s:
            return dict(identity_cache["data"])
        data = {
            "serial": "",
            "serialSource": "",
            "machineId": "",
            "model": "",
            "hostname": "",
            "identitySource": "unavailable",
            "protocolVersion": PROTOCOL_VERSION,
            "features": list(PROTOCOL_FEATURES),
            "server": "rp_server",
            "spkiSha256": device_identity["spkiSha256"],
            "devicePublicKey": device_identity["devicePublicKey"],
            "deviceKeySource": device_identity["deviceKeySource"],
            "tlsSpkiSha256": tls_spki,
            "tlsEnabled": bool(tls_cfg.get("enabled")),
        }
        if tui.enabled and tui.available:
            try:
                ident = await tui.identity()
            except Exception as exc:
                logger.warning("TUI identity query failed: %s", exc)
            else:
                data.update({
                    "serial": ident.get("serial", "") or "",
                    "serialSource": ident.get("serialSource", "") or "",
                    "machineId": ident.get("machineId", "") or "",
                    "model": ident.get("model", "") or "",
                    "hostname": ident.get("hostname", "") or "",
                    "identitySource": "tui",
                })
        elif not tui.enabled:
            data["identitySource"] = "disabled"
        identity_cache.update(at=now, data=data)
        return dict(data)

    # --- protocol ---
    handler = CommandHandler(motors, imu, bms, joy, policy,
                             motor_errors=motor_errors_provider)
    control_cfg = config.get("control", {})
    lease = ControlLease(handler, float(control_cfg.get("lease_ttl_s", 3.0)),
                         float(control_cfg.get("input_timeout_s", 0.5)))
    app.state.control = lease
    lease_holders = set()

    async def guarded_dispatch(session, token, env):
        body = env.WhichOneof("body")
        scope = "read" if body == "query" else "admin" if body == "reset" else "control"
        access.verify(token, scope)
        if body == "query":
            return await handler.handle(env)
        if body == "policy_command" and env.policy_command.action == commands_pb2.PolicyCommand.ACTION_STOP:
            try:
                await lease.stop()
                state = responses_pb2.PolicyResponse.STATE_STOPPED
            except ControlError as exc:
                logger.warning("policy stop failed: %s", exc)
                state = responses_pb2.PolicyResponse.STATE_FAIL
            response = Envelope()
            response.header.timestamp_ms = _now_ms()
            response.policy_response.CopyFrom(
                handler._policy_response(env.policy_command.name, state))
            return [response]
        if body == "stop":
            request_id = env.stop.request_id or secrets.token_hex(8)
            response = Envelope()
            response.header.timestamp_ms = _now_ms()
            response.stop_ack.request_id = request_id
            response.stop_ack.confirmed_at_ms = _now_ms()
            # rp_server can confirm the software stop only. Motor power-off and
            # a physical E-stop are separate states; report them as unknown
            # until a verified source exists.
            response.stop_ack.motor_state = "unknown"
            response.stop_ack.estop_state = "unknown"
            if env.stop.status == "clear":
                await lease.clear_stop()
                response.stop_ack.status = "cleared"
                response.stop_ack.state = auth_pb2.StopAck.STATE_STOPPED
                response.stop_ack.confirmed = True
                response.stop_ack.software_stopped = False
                response.stop_ack.reason = "software stop latch cleared"
            else:
                try:
                    await lease.stop(latch=True)
                    lease_holders.discard(session)
                    response.stop_ack.status = "stopped"
                    response.stop_ack.state = auth_pb2.StopAck.STATE_STOPPED
                    response.stop_ack.confirmed = True
                    response.stop_ack.software_stopped = True
                    response.stop_ack.reason = (
                        "software stop confirmed; motor/e-stop state not verified")
                except ControlError as exc:
                    response.stop_ack.status = "failed"
                    response.stop_ack.state = auth_pb2.StopAck.STATE_FAILED
                    response.stop_ack.confirmed = False
                    response.stop_ack.software_stopped = False
                    response.stop_ack.reason = str(exc)
            return [response]
        return await lease.dispatch(session, env, lambda: access.verify(token, scope))

    async def lease_message(ws, session, token, msg):
        kind = msg.get("type")
        if kind == "heartbeat":
            access.verify(token, "read")
            await lease.heartbeat(session)
            await ws.send_json({"type": "heartbeat", "timestamp": _now_ms()})
        elif kind in ("lease.acquire", "lease.release"):
            access.verify(token, "control")
            result = (await lease.acquire(session, lambda: access.verify(token, "control")) if kind == "lease.acquire"
                      else await lease.release(session))
            if kind == "lease.acquire":
                lease_holders.add(session)
            else:
                lease_holders.discard(session)
            await ws.send_json(result)
        else:
            return False
        return True

    async def session_watchdog(ws, session, token):
        while True:
            await asyncio.sleep(0.05)
            try:
                access.verify(token, "read")
                if lease.owner == session:
                    access.verify(token, "control")
                    await lease.expire()
                    if lease.owner != session:
                        lease_holders.discard(session)
                        await ws.send_json(lease.status("expired"))
                elif session in lease_holders:
                    lease_holders.discard(session)
                    await ws.send_json(lease.status("released"))
            except (AuthError, ControlError):
                try:
                    await lease.release(session, "credential-invalid")
                finally:
                    await ws.close(code=1008)
                return

    # --- monitors ---
    telemetry = TelemetryMonitor(imu, bms, motors, config, mock=mock)

    rp = AppState(
        config=config,
        hardware_status=hardware_status,
        required_hardware=required_hardware,
        motors=motors,
        imu=imu,
        bms=bms,
        joy=joy,
        policy=policy,
        handler=handler,
        telemetry=telemetry,
        mock=mock,
    )
    app.state.rp = rp

    app.state.tui = tui

    def require_tui():
        if not tui.enabled:
            raise TuiError("DISABLED", "tui backend disabled (tui.enabled=false)")
        if not tui.available:
            raise TuiError("UNAVAILABLE", "robopi-tui executable not found")

    # --- transports ---
    transports_enabled = config.get("transports", {"ws": True, "serial": False, "bluetooth": False})

    scfg = config.get("serial", {})
    serial_srv = SerialServer(
        scfg.get("port", "/dev/ttyAMA0"),
        scfg.get("baudrate", 115200),
        handler,
    ) if transports_enabled.get("serial") else None

    bcfg = config.get("bluetooth", {})
    bt_srv = BTServer(handler, channel=bcfg.get("channel", 1)) \
        if transports_enabled.get("bluetooth") else None

    ucfg = config.get("udp", {})
    auth_cfg = ucfg.get("auth", {})
    udp_srv = UDPJoyListener(
        handler,
        host=ucfg.get("host", "0.0.0.0"),
        port=ucfg.get("port", 9000),
        secret_key=auth_cfg.get("secret_key", ""),
        token_ttl=auth_cfg.get("token_ttl", 3600),
        session_timeout=ucfg.get("session_timeout", 10),
        telemetry=telemetry,
    ) if transports_enabled.get("udp") else None

    can_joy_cfg = config.get("can_gamepad", {})
    can_joy_payloads = can_joy_cfg.get("payloads")
    if can_joy_payloads is None:
        if "payload" in can_joy_cfg:
            can_joy_payloads = [can_joy_cfg["payload"]]
        else:
            can_joy_payloads = ["010001AA00000000", "010001AA00000001"]
    can_joy_srv = CANJoyListener(
        handler,
        interface=can_joy_cfg.get("interface", "can_top"),
        can_id=int(can_joy_cfg.get("can_id", 0x003)),
        payloads=tuple(bytes.fromhex(payload) for payload in can_joy_payloads),
        click_ms=int(can_joy_cfg.get("click_ms", 50)),
    ) if can_joy_cfg.get("enabled", False) else None

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
            logger.info("mock: skipping hardware driver init", extra={"event_type": "startup"})
        await telemetry.start()
        if serial_srv:
            await serial_srv.start()
        if bt_srv:
            await bt_srv.start()
        if udp_srv:
            await udp_srv.start()
        if can_joy_srv and not mock:
            await can_joy_srv.start()
        logger.info("rp_server ready mock=%s port_cfg=%s", mock, config.get("server", {}),
                    extra={"event_type": "startup"})

    @app.on_event("shutdown")
    async def on_shutdown():
        await lease.stop()
        if bt_srv:
            await bt_srv.stop()
        if udp_srv:
            udp_srv.stop()
        if can_joy_srv:
            await can_joy_srv.stop()
        if serial_srv:
            await serial_srv.stop()
        await telemetry.stop()
        if policy.running:
            await policy.stop()
        if not mock:
            joy.deinit()
            imu.deinit()
            bms.deinit()
            motors.deinit()

    # ------------------------------------------------------------------
    # REST API
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health():
        ready = True if mock else hardware_ready()
        return {
            "status": "ok" if ready else "degraded",
            "hw_ready": ready,
            "hardware": dict(hardware_status),
            "required_hardware": list(required_hardware),
            "mock": mock,
            "version": __version__,
        }

    @app.get("/sysinfo")
    async def sysinfo():
        import psutil
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
            "motor_errors": await motor_errors_provider(),
            "battery": MessageToDict(telemetry.last_battery.battery) if telemetry.last_battery else None,
            "imu": MessageToDict(telemetry.last_imu.imu) if telemetry.last_imu else None,
        })

    # ------------------------------------------------------------------
    # Board-management backend (robopi-tui JSON-RPC proxy)
    # ------------------------------------------------------------------

    @app.get("/identity")
    async def identity():
        return await board_identity()

    def _local_only(request: Request) -> bool:
        host = request.client.host if request.client else ""
        return host in ("127.0.0.1", "::1", "localhost")

    def _pair_error(exc: PairingError) -> JSONResponse:
        status = {"LOCAL_ONLY": 403, "PAIR_CODE_LOCKED": 429,
                  "PAIR_CODE_INVALID": 400, "PAIR_CODE_EXPIRED": 400,
                  "INVALID_PUBLIC_KEY": 400}.get(exc.code, 400)
        return JSONResponse({"error": {"code": exc.code, "message": str(exc)}},
                            status_code=status)

    def _pair_payload(result: dict, identity: dict) -> dict:
        data = {
            "version": 1,
            "code": result["code"],
            "expiresAt": result["expiresAt"],
            "tlsEnabled": bool(tls_cfg.get("enabled")),
            "tlsSpkiSha256": tls_spki,
            "deviceSpkiSha256": identity.get("spkiSha256"),
            "serial": identity.get("serial", ""),
            "machineId": identity.get("machineId", ""),
        }
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        signature = None
        if jwt_key is not None:
            try:
                signature = base64.b64encode(jwt_key.sign(canonical)).decode("ascii")
            except Exception as exc:
                logger.warning("pairing payload signing failed: %s", exc)
        payload = dict(data, signature=signature)
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode("ascii").rstrip("=")
        return {"payload": payload, "uri": "roboparty://pair?data=" + encoded}

    @app.post("/pair/code")
    async def pair_code(request: Request):
        if not _local_only(request):
            return _pair_error(PairingError("LOCAL_ONLY", "pair code is localhost-only"))
        result = pairing.generate_code()
        result.update(_pair_payload(result, await board_identity()))
        return result

    @app.post("/pair/register")
    async def pair_register(request: Request):
        client = request.client.host if request.client else "unknown"
        window = pair_attempts.setdefault(client, [time.monotonic(), 0])
        if time.monotonic() - window[0] > 60:
            window[:] = [time.monotonic(), 0]
        window[1] += 1
        if window[1] > 10:
            return JSONResponse({"error": {"code": "PAIR_RATE_LIMITED",
                                             "message": "too many pairing attempts"}},
                                status_code=429)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": {"code": "INVALID_PARAMS",
                                             "message": "invalid json"}}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": {"code": "INVALID_PARAMS",
                                             "message": "JSON object required"}}, status_code=400)
        code = str(body.get("code", "")).strip()
        public_key = str(body.get("appPublicKey", "")).strip()
        if not code or not public_key:
            return JSONResponse({"error": {"code": "INVALID_PARAMS",
                                             "message": "code and appPublicKey required"}},
                                status_code=400)
        try:
            app_info = pairing.register(code, public_key, str(body.get("deviceName", "")))
        except PairingError as exc:
            return _pair_error(exc)
        return {"ok": True, **app_info}

    @app.get("/pair/apps")
    async def pair_apps(request: Request):
        if not _local_only(request):
            return _pair_error(PairingError("LOCAL_ONLY", "app list is localhost-only"))
        return {"apps": pairing.list_apps()}

    @app.post("/pair/revoke")
    async def pair_revoke(request: Request):
        if not _local_only(request):
            return _pair_error(PairingError("LOCAL_ONLY", "revoke is localhost-only"))
        try:
            body = await request.json()
        except Exception:
            body = {}
        app_key_id = str((body or {}).get("appKeyId", "")).strip()
        if not app_key_id:
            return JSONResponse({"error": {"code": "INVALID_PARAMS",
                                             "message": "appKeyId required"}}, status_code=400)
        return {"ok": pairing.revoke(app_key_id)}

    @app.get("/tui/health")
    async def tui_health():
        return {
            "enabled": tui.enabled,
            "available": tui.available,
            "executable": tui.executable,
            "server": tui.server,
            "allow_jobs": tui.allow_jobs,
        }

    @app.get("/tui/tasks")
    async def tui_tasks():
        try:
            require_tui()
            return await tui.tasks()
        except TuiError as exc:
            return _tui_error_response(exc)

    @app.get("/tui/tasks/{task_id}")
    async def tui_task(task_id: str):
        try:
            require_tui()
            return await tui.describe(task_id)
        except TuiError as exc:
            return _tui_error_response(exc)

    @app.get("/tui/snapshot")
    async def tui_snapshot():
        try:
            require_tui()
            return await tui.snapshot()
        except TuiError as exc:
            return _tui_error_response(exc)

    @app.get("/tui/jobs")
    async def tui_jobs(limit: int = 20):
        try:
            require_tui()
            return await tui.jobs(max(1, min(int(limit), 100)))
        except TuiError as exc:
            return _tui_error_response(exc)

    @app.get("/tui/jobs/active")
    async def tui_active_job():
        try:
            require_tui()
            return await tui.active_job()
        except TuiError as exc:
            return _tui_error_response(exc)

    @app.get("/tui/jobs/{job_id}")
    async def tui_job(job_id: str):
        try:
            require_tui()
            return await tui.job(job_id)
        except TuiError as exc:
            return _tui_error_response(exc)

    @app.post("/tui/jobs")
    async def tui_start_job(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": {"code": "INVALID_PARAMS", "message": "invalid json"}},
                status_code=400,
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": {"code": "INVALID_PARAMS", "message": "JSON object required"}},
                status_code=400,
            )
        task_id = str(body.get("taskId", "")).strip()
        if not task_id:
            return JSONResponse(
                {"error": {"code": "INVALID_PARAMS", "message": "taskId required"}},
                status_code=400,
            )
        try:
            require_tui()
            return await tui.start_job(task_id, body.get("requestId"))
        except TuiError as exc:
            return _tui_error_response(exc)

    @app.post("/tui/jobs/{job_id}/acknowledge")
    async def tui_acknowledge(job_id: str):
        try:
            require_tui()
            return await tui.acknowledge(job_id)
        except TuiError as exc:
            return _tui_error_response(exc)

    # ------------------------------------------------------------------
    # JSON WebSocket gateway for the legacy-style app (WSS when TLS is on)
    # ------------------------------------------------------------------

    async def _auth_fail(ws: WebSocket, reason: str):
        logger.warning("auth failed: %s", reason, extra={"event_type": "auth"})
        try:
            await ws.send_json({"type": "auth_result", "ok": False, "reason": reason})
        except Exception:
            pass
        try:
            await ws.close(code=1008)
        except Exception:
            pass

    @app.websocket("/ws-json")
    async def ws_json(ws: WebSocket):
        await ws.accept()
        if jwt_key is None:
            await _auth_fail(ws, "server identity unavailable")
            return
        try:
            first = await asyncio.wait_for(ws.receive_json(), 10)
        except Exception:
            await _auth_fail(ws, "auth request required")
            return
        if not isinstance(first, dict) or first.get("type") != "auth_request":
            await _auth_fail(ws, "auth request required")
            return
        app_key_id = str(first.get("device_id", "")).strip()
        app = pairing.get_app(app_key_id) if app_key_id else None
        if not app or app.get("revoked"):
            await _auth_fail(ws, "app key is not paired or was revoked")
            return
        challenge = secrets.token_hex(16)
        await ws.send_json({"type": "challenge", "challenge_code": challenge,
                            "timestamp": _now_ms()})
        try:
            response = await asyncio.wait_for(ws.receive_json(), 10)
        except Exception:
            await _auth_fail(ws, "challenge response timeout")
            return
        if (not isinstance(response, dict)
                or response.get("type") != "challenge_response"
                or str(response.get("device_id", "")) != app_key_id
                or not verify_app_signature(app, f"{app_key_id}:{challenge}",
                                            str(response.get("signature", "")))):
            await _auth_fail(ws, "invalid challenge signature")
            return
        scopes = list(app.get("scopes", []))
        if "read" not in scopes:
            await _auth_fail(ws, "read scope required")
            return
        session_token, expires_ms = issue_token(jwt_key, app_key_id, scopes)
        await ws.send_json({"type": "auth_result", "ok": True,
                            "token": session_token, "expires_at": expires_ms,
                            "protocol_version": PROTOCOL_VERSION,
                            "features": list(PROTOCOL_FEATURES)})
        logger.info("JSON WSS authenticated: app=%s", app_key_id, extra={"event_type": "auth"})

        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        telemetry.add_client(queue)

        async def sender():
            while True:
                env = await queue.get()
                payload = telemetry_json(env)
                if payload:
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        break

        send_task = asyncio.create_task(sender())
        session = secrets.token_hex(16)
        watch_task = asyncio.create_task(session_watchdog(ws, session, session_token))

        def claims_for(msg: dict) -> dict:
            token = str(msg.get("token") or session_token)
            if token != session_token:
                raise AuthError("INVALID_TOKEN", "token must belong to this session")
            return access.verify(token)

        try:
            while True:
                msg = await ws.receive_json()
                if not isinstance(msg, dict):
                    continue
                try:
                    claims_for(msg)
                except AuthError:
                    await _auth_fail(ws, "token expired or invalid")
                    break
                kind = msg.get("type")
                try:
                    if await lease_message(ws, session, session_token, msg):
                        continue
                    if kind == "control":
                        await guarded_dispatch(session, session_token, control_envelope(msg))
                    elif kind == "stop":
                        status = str(msg.get("status", ""))
                        request_id = str(msg.get("request_id", "") or secrets.token_hex(8))
                        if status == "request":
                            access.verify(session_token, "control")
                            try:
                                await lease.stop(latch=True)
                                lease_holders.discard(session)
                                await ws.send_json({
                                    "type": "stop", "status": "stopped",
                                    "request_id": request_id, "state": "STOPPED",
                                    "confirmed": True,
                                    "reason": "process exited and stop confirmed",
                                    "timestamp": _now_ms()})
                            except ControlError as exc:
                                await ws.send_json({
                                    "type": "stop", "status": "failed",
                                    "request_id": request_id, "state": "FAIL",
                                    "confirmed": False, "reason": str(exc),
                                    "timestamp": _now_ms()})
                        elif status == "clear":
                            access.verify(session_token, "control")
                            await lease.clear_stop()
                            await ws.send_json({"type": "stop", "status": "cleared",
                                                "request_id": request_id,
                                                "state": "STOPPED", "confirmed": True,
                                                "reason": "software stop latch cleared",
                                                "timestamp": _now_ms()})
                    elif kind == "skill_action":
                        await guarded_dispatch(session, session_token, skill_envelope(msg))
                        request_id = str(msg.get("request_id", ""))
                        await ws.send_json({"type": "skill_action_ack_received",
                                            "request_id": request_id,
                                            "timestamp": _now_ms()})
                        # There is no skill executor yet: never claim physical completion.
                        logger.info("skill action unsupported: request=%s", request_id,
                                    extra={"event_type": "skill"})
                        await ws.send_json({"type": "skill_action_ack_completed",
                                            "request_id": request_id,
                                            "status": "unsupported", "execution_time_ms": 0,
                                            "timestamp": _now_ms()})
                except (AuthError, ControlError) as exc:
                    await ws.send_json({"type": "error", "code": exc.code, "message": str(exc)})
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.debug("JSON WS session ended: %s", exc)
        finally:
            watch_task.cancel()
            send_task.cancel()
            await asyncio.gather(watch_task, send_task, return_exceptions=True)
            telemetry.remove_client(queue)
            await lease.release(session, "disconnect")
            lease_holders.discard(session)

    # ------------------------------------------------------------------
    # WebSocket — one protobuf Envelope per binary frame
    # ------------------------------------------------------------------

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        try:
            token = access.bearer(ws.headers.get("authorization"))
            access.verify(token, "read")
        except AuthError:
            await ws.close(code=1008)
            return
        client_addr = ws.client.host if ws.client else "unknown"
        subprotocol = ws.headers.get("sec-websocket-protocol", "")
        if "roboparty.v2.proto" not in [item.strip() for item in subprotocol.split(",")]:
            await ws.close(code=1002)
            return
        logger.info("WebSocket 连接建立: %s", client_addr, extra={"event_type": "connection"})
        connect_time = time.time()

        await ws.accept(subprotocol="roboparty.v2.proto")
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        telemetry.add_client(q)

        async def sender():
            while True:
                env = await q.get()
                try:
                    await ws.send_bytes(CODEC.encode(env))
                except Exception:
                    break

        send_task = asyncio.create_task(sender())
        session = secrets.token_hex(16)
        watch_task = asyncio.create_task(session_watchdog(ws, session, token))
        try:
            await ws.send_bytes(CODEC.encode(
                _conn_envelope(True, True if mock else hardware_ready())))
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("text") is not None:
                    try:
                        msg = json.loads(message["text"])
                        if not isinstance(msg, dict) or not await lease_message(ws, session, token, msg):
                            raise ControlError("INVALID_MESSAGE", "expected lease or heartbeat message")
                    except (ValueError, AuthError, ControlError) as exc:
                        await ws.send_json({"type": "error", "code": getattr(exc, "code", "INVALID_MESSAGE"),
                                            "message": str(exc)})
                    continue
                raw = message.get("bytes")
                if raw is None:
                    continue
                try:
                    env = CODEC.decode(raw)
                except Exception:
                    logger.debug("WS: invalid protobuf frame (%d bytes)", len(raw))
                    continue
                body = env.WhichOneof("body")
                packet_logger.info("WS_RECV src=%s body=%s size=%d",
                                   client_addr, body, len(raw))
                if body is None:
                    continue
                try:
                    for resp in await guarded_dispatch(session, token, env):
                        await ws.send_bytes(CODEC.encode(resp))
                except (AuthError, ControlError) as exc:
                    await ws.send_json({"type": "error", "code": exc.code, "message": str(exc)})
                except Exception as exc:
                    logger.warning("命令执行失败: %s (body=%s)", exc, body,
                                   extra={"event_type": "command"})
        except WebSocketDisconnect:
            pass
        finally:
            watch_task.cancel()
            send_task.cancel()
            await asyncio.gather(watch_task, send_task, return_exceptions=True)
            telemetry.remove_client(q)
            await lease.release(session, "disconnect")
            lease_holders.discard(session)
            duration = time.time() - connect_time
            logger.info("WebSocket 连接断开: %s (时长: %.1fs)", client_addr, duration,
                        extra={"event_type": "connection"})

    return app
