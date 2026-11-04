# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""UDP listener: receive protobuf Envelopes → dispatch to robot.

Datagram format: ``UDP_MAGIC`` + ``UDP_VERSION`` + serialized ``Envelope``
(see protocol/codec.py). Auth/session/heartbeat/stop live here; robot commands
are delegated to ``CommandHandler``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

from ..protocol import PROTOCOL_FEATURES, PROTOCOL_VERSION
from ..protocol.codec import Envelope, frame_udp, unframe_udp
from ..auth.udp_auth import UDPAuthenticator
from ..auth.udp_session import SessionManager, SessionState, UDPSession

logger = logging.getLogger("rp_server.udp")
packet_logger = logging.getLogger("rp_server.packets")

STOP_ACK_INTERVAL = 0.02
STOP_ACK_MAX_SECONDS = 30.0
STOP_SCRIPT = os.environ.get(
    "RP_STOP_SCRIPT",
    "/opt/roboparty/share/roboparty-rp-server/scripts/stop_robot.sh",
)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class UDPJoyListener:
    """Async UDP listener with auth, heartbeat and session management."""

    def __init__(
        self,
        handler: Any,
        host: str = "0.0.0.0",
        port: int = 9000,
        secret_key: str = "",
        token_ttl: int = 3600,
        session_timeout: float = 10.0,
        telemetry: Any = None,
    ):
        self._handler = handler
        self._host = host
        self._port = port
        self._transport: Optional[asyncio.DatagramTransport] = None

        self._auth = UDPAuthenticator(secret_key, token_ttl)
        self._sessions = SessionManager(timeout=session_timeout)
        self._telemetry = telemetry

        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._telemetry_tasks: dict[str, asyncio.Task] = {}
        self._stop_ack_tasks: dict[str, asyncio.Task] = {}
        self._software_stop_task: Optional[asyncio.Task] = None
        self._stop_latched = False
        self._joy_owner: Optional[str] = None

    # ------------------------------------------------------------------
    # asyncio Datagram protocol
    # ------------------------------------------------------------------

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport
        logger.info("UDP listener ready on %s:%d", self._host, self._port)

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        self._sessions.update_activity(addr)
        env = unframe_udp(data)
        if env is None:
            logger.debug("UDP: dropped non-v1 datagram (%d bytes) from %s:%d",
                         len(data), addr[0], addr[1])
            return
        packet_logger.info("UDP_RECV src=%s:%d size=%d body=%s",
                           addr[0], addr[1], len(data), env.WhichOneof("body"))
        try:
            self._process(env, addr)
        except Exception:
            logger.debug("UDP 数据包处理失败: %s:%d", addr[0], addr[1], exc_info=True)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UDP error: %s", exc)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        logger.info("UDP listener stopped")
        self._transport = None

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: self,
            local_addr=(self._host, self._port),
        )
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        for task in self._telemetry_tasks.values():
            task.cancel()
        self._telemetry_tasks.clear()
        for task in self._stop_ack_tasks.values():
            task.cancel()
        self._stop_ack_tasks.clear()
        if self._transport:
            self._transport.close()
            self._transport = None

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(1)
                for session in self._sessions.connected_sessions:
                    self._send_heartbeat(session.addr)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("心跳发送失败", exc_info=True)

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(5)
                expired_sessions = self._sessions.cleanup_expired()
                expired_auth = self._auth.cleanup_expired()
                joy = getattr(self._handler, "joy", None)
                for session in expired_sessions:
                    task = self._telemetry_tasks.pop(session.addr_key, None)
                    if task:
                        task.cancel()
                    ack_task = self._stop_ack_tasks.pop(session.addr_key, None)
                    if ack_task:
                        ack_task.cancel()
                    if (
                        joy is not None
                        and session.state == SessionState.CONNECTED
                        and session.addr_key == self._joy_owner
                    ):
                        joy.reset()
                        self._joy_owner = None
                        logger.info("会话超时，摇杆已归零: %s", session.addr_key)
                if expired_sessions or expired_auth:
                    logger.info("清理: 会话 %d 个, 认证 %d 个", len(expired_sessions), expired_auth)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("会话清理失败", exc_info=True)

    async def _telemetry_loop(self, addr: tuple, addr_key: str) -> None:
        last_motor_send = 0.0
        try:
            while True:
                await asyncio.sleep(0.02)
                if not self._telemetry:
                    continue
                if self._telemetry.last_imu is not None:
                    self._send(self._telemetry.last_imu, addr)
                if self._telemetry.last_battery is not None:
                    self._send(self._telemetry.last_battery, addr)
                now = time.monotonic()
                if now - last_motor_send >= 1.0 and self._telemetry.last_motors is not None:
                    self._send(self._telemetry.last_motors, addr)
                    last_motor_send = now
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("遥测发送失败: %s", addr_key, exc_info=True)

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    def _process(self, env: Envelope, addr: tuple) -> None:
        body = env.WhichOneof("body")
        if body == "auth_request":
            self._handle_auth_request(env.auth_request, addr)
        elif body == "challenge_response":
            self._handle_challenge_response(env.challenge_response, addr)
        elif body == "stop":
            self._handle_stop(env, addr)
        elif body == "control":
            self._handle_control(env, addr)
        elif body == "heartbeat":
            self._handle_heartbeat(env.heartbeat, addr)
        elif body == "skill_action":
            self._handle_skill_action(env, addr)
        elif body is not None:
            logger.debug("UDP: ignoring body %r from %s:%d", body, addr[0], addr[1])

    def _handle_auth_request(self, req, addr: tuple) -> None:
        if not req.device_id:
            logger.warning("认证请求缺少 device_id: %s:%d", addr[0], addr[1])
            return
        session = UDPSession(
            addr=addr,
            device_id=req.device_id,
            device_name=req.device_name,
            state=SessionState.AUTHENTICATING,
        )
        self._sessions.add_session(session)
        challenge_code = self._auth.generate_challenge(addr, req.device_id)
        env = Envelope()
        env.header.timestamp_ms = _now_ms()
        env.challenge.challenge_code = challenge_code
        env.challenge.timestamp_ms = _now_ms()
        self._send(env, addr)

    def _handle_challenge_response(self, resp, addr: tuple) -> None:
        if not resp.device_id or not resp.signature:
            return
        token = self._auth.verify_signature(addr, resp.device_id, resp.signature)
        env = Envelope()
        env.header.timestamp_ms = _now_ms()
        if token:
            self._sessions.set_connected(addr, token)
            addr_key = f"{addr[0]}:{addr[1]}"
            if self._telemetry and addr_key not in self._telemetry_tasks:
                self._telemetry_tasks[addr_key] = asyncio.create_task(
                    self._telemetry_loop(addr, addr_key)
                )
            env.auth_result.ok = True
            env.auth_result.token = token
            env.auth_result.expires_at_ms = int((time.time() + self._auth._token_ttl) * 1000)
            env.auth_result.protocol_version = PROTOCOL_VERSION
            env.auth_result.features.extend(PROTOCOL_FEATURES)
            logger.info("认证成功: device=%s", resp.device_id)
        else:
            env.auth_result.ok = False
        self._send(env, addr)

    def _handle_stop(self, env: Envelope, addr: tuple) -> None:
        """Authenticated software stop; ack is repeated until confirmed.

        ``status`` semantics:
          - ``""``      : request stop (token required)
          - ``received``: client confirmed the ack, stop repeating
          - ``clear``   : operator explicitly clears the stop latch (token required)
        """
        req = env.stop
        addr_key = f"{addr[0]}:{addr[1]}"
        status = req.status

        if status == "received":
            task = self._stop_ack_tasks.pop(addr_key, None)
            if task:
                task.cancel()
            logger.info("software stop acknowledgment confirmed by %s", addr_key)
            return

        if status == "clear":
            if not self._authorize(req.token, env, addr):
                logger.warning("rejected unauthorized stop clear from %s", addr_key)
                return
            task = self._stop_ack_tasks.pop(addr_key, None)
            if task:
                task.cancel()
            self._stop_latched = False
            logger.warning("software stop latch cleared by %s", addr_key)
            return

        if status:
            logger.debug("UDP: ignoring invalid stop status %r from %s", status, addr_key)
            return

        if not self._authorize(req.token, env, addr):
            logger.warning("rejected unauthorized software stop from %s", addr_key)
            return

        if not self._stop_latched:
            self._stop_latched = True
            joy = getattr(self._handler, "joy", None)
            if joy is not None:
                joy.reset()
            self._software_stop_task = asyncio.create_task(self._run_software_stop())
            logger.warning("software stop latched by %s", addr_key)

        task = self._stop_ack_tasks.get(addr_key)
        if task is None or task.done():
            self._stop_ack_tasks[addr_key] = asyncio.create_task(
                self._repeat_stop_ack(addr, addr_key)
            )

    async def _repeat_stop_ack(self, addr: tuple, addr_key: str) -> None:
        deadline = time.monotonic() + STOP_ACK_MAX_SECONDS
        try:
            while time.monotonic() < deadline:
                env = Envelope()
                env.header.timestamp_ms = _now_ms()
                env.stop_ack.status = "accepted"
                self._send(env, addr)
                await asyncio.sleep(STOP_ACK_INTERVAL)
            logger.warning("software stop ack timeout (%ss) for %s",
                           STOP_ACK_MAX_SECONDS, addr_key)
        except asyncio.CancelledError:
            pass
        finally:
            current = asyncio.current_task()
            if self._stop_ack_tasks.get(addr_key) is current:
                self._stop_ack_tasks.pop(addr_key, None)

    async def _run_software_stop(self) -> None:
        try:
            if not os.path.isfile(STOP_SCRIPT):
                logger.error("software stop script not found: %s", STOP_SCRIPT)
                return
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash",
                STOP_SCRIPT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.warning(
                    "software stop script finished: %s",
                    stdout.decode(errors="replace").strip(),
                )
            else:
                logger.error(
                    "software stop script failed rc=%d stderr=%s",
                    proc.returncode,
                    stderr.decode(errors="replace").strip(),
                )
        except Exception:
            logger.exception("failed to execute software stop script")
        finally:
            self._software_stop_task = None

    def _handle_control(self, env: Envelope, addr: tuple) -> None:
        if self._stop_latched:
            return
        if not self._authorize(env.control.token, env, addr):
            return
        self._joy_owner = f"{addr[0]}:{addr[1]}"
        # Reuse the command handler for the actual axis/button application.
        asyncio.ensure_future(self._handler.handle(env))

    def _handle_heartbeat(self, hb, addr: tuple) -> None:
        if not hb.token:
            return
        if not self._auth.verify_token(hb.token):
            return
        self._sessions.update_heartbeat(addr)

    def _handle_skill_action(self, env: Envelope, addr: tuple) -> None:
        if self._stop_latched:
            return
        if not self._authorize(None, env, addr, require_token=False):
            return
        action = env.skill_action
        session = self._sessions.get_session(addr)
        logger.info("技能动作: action=%s request=%s seq=%s device=%s",
                    action.action_id, action.request_id, action.sequence,
                    session.device_id if session else "")
        # TODO: 处理技能动作逻辑（当前仅记录）

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _session_ok(self, addr: tuple) -> bool:
        session = self._sessions.get_session(addr)
        return bool(session and session.state == SessionState.CONNECTED)

    def _authorize(self, token: str, env: Envelope, addr: tuple, require_token: bool = True) -> bool:
        """Token + session + replay validation. Returns True when allowed."""
        if not token:
            if require_token:
                return False
        else:
            if not self._auth.verify_token(token):
                return False
            if not self._session_ok(addr):
                return False

        session = self._sessions.get_session(addr)
        if session is None:
            return False

        header = env.header
        timestamp = header.timestamp_ms
        if timestamp:
            if timestamp <= session.last_control_timestamp:
                return False
        sequence = header.sequence
        if sequence and sequence <= session.sequence:
            return False

        if timestamp:
            session.last_control_timestamp = timestamp
        if sequence:
            session.sequence = sequence
        return True

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    def _send(self, env: Envelope, addr: tuple) -> None:
        if not self._transport:
            return
        try:
            self._transport.sendto(frame_udp(env), addr)
        except Exception:
            logger.debug("UDP 发送失败: %s:%d", addr[0], addr[1], exc_info=True)

    def _send_heartbeat(self, addr: tuple) -> None:
        env = Envelope()
        env.header.timestamp_ms = _now_ms()
        env.heartbeat.SetInParent()
        self._send(env, addr)
