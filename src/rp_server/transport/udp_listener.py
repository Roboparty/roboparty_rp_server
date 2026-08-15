# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""UDP listener: receive App JSON → translate to AT commands → dispatch to robot.

Data format (App UDP joystick protocol):

    {"type":"control", "sequence":1, "timestamp":..., "token":"...",
     "left_stick_x":0.0, "left_stick_y":0.0,
     "right_stick_x":0.0, "right_stick_y":0.0,
     "btn_a":false, "btn_b":false, "btn_x":false, "btn_y":false,
     "dpad_up":false, "dpad_down":false, "dpad_left":false, "dpad_right":false}

Also accepts legacy format (without "type"/"token" fields).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from ..protocol.at_parser import AtCommand, CmdType
from ..udp_auth import UDPAuthenticator
from ..udp_session import SessionManager, SessionState, UDPSession

logger = logging.getLogger("rp_server.udp")
packet_logger = logging.getLogger("rp_server.packets")

# Axis name mapping: JSON field → AT+JOY axis name
_AXIS_MAP: dict[str, str] = {
    "left_stick_x": "lx",
    "left_stick_y": "ly",
    "right_stick_x": "rx",
    "right_stick_y": "ry",
}

# Button name mapping: JSON field → AT+BTN button name
_BTN_MAP: dict[str, str] = {
    "btn_a": "a",
    "btn_b": "b",
    "btn_x": "x",
    "btn_y": "y",
    "dpad_up": "du",
    "dpad_down": "dd",
    "dpad_left": "dl",
    "dpad_right": "dr",
}

# Dead zone: joystick values within ±DEAD_ZONE are ignored
DEAD_ZONE = 0.01


class UDPJoyListener:
    """Async UDP listener with auth, heartbeat and session management."""

    def __init__(
        self,
        at_handler: Any,
        host: str = "0.0.0.0",
        port: int = 9000,
        secret_key: str = "",
        token_ttl: int = 3600,
        session_timeout: float = 10.0,
        telemetry: Any = None,
    ):
        self._handler = at_handler
        self._host = host
        self._port = port
        self._transport: Optional[asyncio.DatagramTransport] = None

        # 认证管理
        self._auth = UDPAuthenticator(secret_key, token_ttl)
        # 会话管理
        self._sessions = SessionManager(timeout=session_timeout)
        # 遥测数据源
        self._telemetry = telemetry
        # 按钮状态（按会话地址隔离）
        self._btn_state: dict[str, dict[str, bool]] = {}
        self._btn_seq: dict[str, int] = {}

        # 定时任务
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._telemetry_tasks: dict[str, asyncio.Task] = {}  # addr_key → task

    # ------------------------------------------------------------------
    # Connection protocol (asyncio Datagram)
    # ------------------------------------------------------------------

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport
        logger.info("UDP listener ready on %s:%d", self._host, self._port)

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        """Called by asyncio on each incoming UDP packet."""
        # 记录原始数据包内容
        packet_logger.info(
            "UDP_RECV src=%s:%d size=%d data=%s",
            addr[0], addr[1], len(data), data.decode("utf-8", errors="replace").strip()
        )
        self._sessions.update_activity(addr)
        try:
            self._process(data, addr)
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
        # 启动心跳和清理任务
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
        if self._transport:
            self._transport.close()
            self._transport = None

    async def _heartbeat_loop(self) -> None:
        """每秒向已连接会话发送心跳"""
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
        """每5秒清理超时会话"""
        while True:
            try:
                await asyncio.sleep(5)
                expired_sessions = self._sessions.cleanup_expired()
                expired_auth = self._auth.cleanup_expired()
                # 停止已过期会话的遥测任务
                for session in expired_sessions:
                    task = self._telemetry_tasks.pop(session.addr_key, None)
                    if task:
                        task.cancel()
                if expired_sessions or expired_auth:
                    logger.info("清理: 会话 %d 个, 认证 %d 个", len(expired_sessions), expired_auth)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("会话清理失败", exc_info=True)

    async def _telemetry_loop(self, addr: tuple, addr_key: str) -> None:
        """定期发送遥测数据给已连接客户端"""
        try:
            while True:
                await asyncio.sleep(1)  # 每秒发送一次
                if not self._telemetry:
                    continue

                # 发送电池数据
                battery = self._telemetry.last_battery
                if battery:
                    self._send_json({
                        "type": "battery",
                        "voltage": battery["voltage"],
                        "current": battery["current"],
                        "soc": battery["soc"],
                        "temp": battery["temp"],
                    }, addr)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("遥测发送失败: %s", addr_key, exc_info=True)

    # ------------------------------------------------------------------
    # Packet processing
    # ------------------------------------------------------------------

    def _process(self, data: bytes, addr: tuple) -> None:
        text = data.decode("utf-8", errors="replace").strip()
        if not text:
            return

        try:
            pkt: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            logger.debug("UDP: invalid JSON (%d bytes)", len(data))
            return

        msg_type = pkt.get("type", "")

        # 消息分发
        if msg_type == "auth_request":
            self._handle_auth_request(pkt, addr)
        elif msg_type == "challenge_response":
            self._handle_challenge_response(pkt, addr)
        elif msg_type == "control":
            self._handle_control(pkt, addr)
        elif msg_type == "heartbeat":
            self._handle_heartbeat(pkt, addr)
        elif msg_type == "skill_action":
            self._handle_skill_action(pkt, addr)
        elif not msg_type:
            # 兼容旧格式（无type字段视为control）
            self._handle_control(pkt, addr)

    def _handle_auth_request(self, pkt: dict, addr: tuple) -> None:
        """处理认证请求"""
        device_id = pkt.get("device_id", "")
        device_name = pkt.get("device_name", "")

        if not device_id:
            logger.warning("认证请求缺少 device_id: %s:%d", addr[0], addr[1])
            return

        session = UDPSession(
            addr=addr,
            device_id=device_id,
            device_name=device_name,
            state=SessionState.AUTHENTICATING,
        )
        self._sessions.add_session(session)

        challenge_code = self._auth.generate_challenge(addr, device_id)
        self._send_json({
            "type": "challenge",
            "challenge_code": challenge_code,
            "timestamp": int(time.time() * 1000),
        }, addr)

    def _handle_challenge_response(self, pkt: dict, addr: tuple) -> None:
        """处理挑战响应"""
        device_id = pkt.get("device_id", "")
        signature = pkt.get("signature", "")

        if not device_id or not signature:
            return

        token = self._auth.verify_signature(addr, device_id, signature)
        if token:
            self._sessions.set_connected(addr, token)
            addr_key = f"{addr[0]}:{addr[1]}"
            self._btn_state[addr_key] = {}
            self._btn_seq[addr_key] = 0

            # 启动遥测数据发送
            if self._telemetry and addr_key not in self._telemetry_tasks:
                self._telemetry_tasks[addr_key] = asyncio.create_task(
                    self._telemetry_loop(addr, addr_key)
                )

            self._send_json({
                "type": "auth_result",
                "ok": True,
                "token": token,
                "expires_at": int((time.time() + self._auth._token_ttl) * 1000),
            }, addr)
            logger.info("认证成功: device=%s", device_id)
        else:
            self._send_json({
                "type": "auth_result",
                "ok": False,
                "reason": "签名验证失败",
            }, addr)

    def _handle_control(self, pkt: dict, addr: tuple) -> None:
        """处理控制指令"""
        # 验证 Token
        token = pkt.get("token", "")
        if token:
            payload = self._auth.verify_token(token)
            if not payload:
                return
            session = self._sessions.get_session(addr)
            if not session or session.state != SessionState.CONNECTED:
                return

            # 序列号校验
            seq = pkt.get("sequence", 0)
            if isinstance(seq, (int, float)):
                seq = int(seq)
                if seq and seq <= session.sequence:
                    return
                if seq:
                    session.sequence = seq

        addr_key = f"{addr[0]}:{addr[1]}"

        # Axes → AT+JOY
        for json_key, at_axis in _AXIS_MAP.items():
            val = pkt.get(json_key, 0.0)
            if not isinstance(val, (int, float)):
                continue
            if -DEAD_ZONE < val < DEAD_ZONE:
                continue
            clamped = max(-1.0, min(1.0, float(val)))
            self._dispatch(f"AT+JOY={at_axis},{clamped:.3f}")

        # Buttons → AT+BTN (only on state change)
        for json_key, at_name in _BTN_MAP.items():
            pressed = bool(pkt.get(json_key, False))
            prev = self._btn_state.get(addr_key, {}).get(at_name, False)
            if pressed == prev:
                continue
            self._btn_state.setdefault(addr_key, {})[at_name] = pressed
            self._btn_seq[addr_key] = self._btn_seq.get(addr_key, 0) + 1
            state = "down" if pressed else "up"
            self._dispatch(f"AT+BTN={at_name},{state},{self._btn_seq[addr_key]}")

    def _handle_heartbeat(self, pkt: dict, addr: tuple) -> None:
        """处理客户端心跳"""
        token = pkt.get("token", "")
        if not token:
            return
        payload = self._auth.verify_token(token)
        if not payload:
            return
        self._sessions.update_heartbeat(addr)

    def _handle_skill_action(self, pkt: dict, addr: tuple) -> None:
        """处理技能动作请求"""
        # 验证 Token
        token = pkt.get("token", "")
        if not token:
            logger.debug("技能动作缺少 token: %s:%d", addr[0], addr[1])
            return

        payload = self._auth.verify_token(token)
        if not payload:
            logger.debug("技能动作 token 无效: %s:%d", addr[0], addr[1])
            return

        # 检查会话状态
        session = self._sessions.get_session(addr)
        if not session or session.state != SessionState.CONNECTED:
            logger.debug("技能动作会话未连接: %s:%d", addr[0], addr[1])
            return

        # 提取技能动作信息
        action_id = pkt.get("action_id", "")
        request_id = pkt.get("request_id", "")
        sequence = pkt.get("sequence", 0)

        logger.info("技能动作: action=%s request=%s seq=%s device=%s",
                    action_id, request_id, sequence, session.device_id)

        # TODO: 处理技能动作逻辑
        # 目前只记录日志，后续可扩展为执行具体动作

    def _send_json(self, data: dict, addr: tuple) -> None:
        """发送 JSON 数据"""
        if not self._transport:
            return
        try:
            msg = json.dumps(data).encode("utf-8")
            self._transport.sendto(msg, addr)
            packet_logger.info(
                "UDP_SEND dst=%s:%d data=%s",
                addr[0], addr[1], json.dumps(data)
            )
        except Exception:
            logger.debug("UDP 发送失败: %s:%d", addr[0], addr[1], exc_info=True)

    def _send_heartbeat(self, addr: tuple) -> None:
        """发送心跳响应"""
        self._send_json({
            "type": "heartbeat",
            "timestamp": int(time.time() * 1000),
        }, addr)

    def _dispatch(self, raw: str) -> None:
        """Parse raw AT line and feed into the handler (fire-and-forget)."""
        cmd = AtCommand.parse(raw)
        if cmd is None:
            return
        try:
            # Dispatch synchronously — all AT handlers are synchronous
            for _ in self._handler.dispatch(cmd):
                pass  # UDP doesn't need to send responses back
        except Exception:
            logger.debug("AT dispatch failed for %r", raw, exc_info=True)
