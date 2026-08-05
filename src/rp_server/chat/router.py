# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""LLM chat REST API with multi-turn memory + robot sensor context."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth.router import require_auth
from .deepseek import DeepSeekClient

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: Optional[str] = None
    model: Optional[str] = None


def _chat_cfg(request: Request) -> dict:
    return request.app.state.rp.config.get("chat", {})


def _resolve_model(cfg: dict, requested: Optional[str]) -> str:
    default = cfg.get("model", "deepseek-v4-flash")
    if not requested:
        return default
    allowed = [
        m["id"] if isinstance(m, dict) else str(m)
        for m in cfg.get("models", [])
    ]
    if allowed and requested not in allowed:
        raise HTTPException(400, f"unsupported model: {requested}")
    return requested


def _build_robot_context(request: Request) -> str:
    rp = request.app.state.rp
    parts = ["You are the RoboParty robot assistant. Use the live robot status below."]
    telemetry = rp.telemetry
    motors = rp.motors
    policy = rp.policy
    parts.append(f"hw_ready={bool(motors and motors.ready)}")
    if policy is not None:
        parts.append(f"policy={policy.name or 'none'} running={policy.running}")
    if telemetry and telemetry.last_battery:
        b = telemetry.last_battery
        parts.append(
            f"battery V={b.get('voltage')} A={b.get('current')} "
            f"SoC={b.get('soc')}% temp={b.get('temp')}"
        )
    if telemetry and telemetry.last_imu:
        imu = telemetry.last_imu
        parts.append(f"imu quat={imu.get('quat')} temp={imu.get('temp')}")
    if telemetry and telemetry.last_errors:
        parts.append(f"motor_errors={telemetry.last_errors}")
    else:
        parts.append("motor_errors=none")
    return "\n".join(parts)


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, _user=Depends(require_auth)):
    rp = request.app.state.rp
    cfg = _chat_cfg(request)
    if not cfg.get("enabled", True) or rp.chat_store is None:
        raise HTTPException(503, "chat disabled")

    store = rp.chat_store
    session = store.get_or_create(body.session_id)

    if cfg.get("inject_robot_context", True):
        system = _build_robot_context(request)
        if not session.messages or session.messages[0].get("role") != "system":
            store.append(session, "system", system)
        else:
            session.messages[0]["content"] = system

    store.append(session, "user", body.message)

    model = _resolve_model(cfg, body.model)
    api_key = os.environ.get("RP_DEEPSEEK_API_KEY") or cfg.get("api_key", "")
    client = DeepSeekClient(
        api_key=api_key,
        api_base=cfg.get("api_base", "https://api.deepseek.com/v1"),
        model=model,
    )

    if not client.configured:
        # Dev-friendly echo when key missing (still multi-turn)
        reply = (
            f"[mock-llm] session={session.session_id} "
            f"turns={len([m for m in session.messages if m['role']=='user'])} "
            f"echo={body.message}"
        )
    else:
        try:
            reply = client.chat(store.as_openai_messages(session))
        except RuntimeError as exc:
            raise HTTPException(502, str(exc))

    store.append(session, "assistant", reply)
    return {
        "ok": True,
        "session_id": session.session_id,
        "reply": reply,
        "model": model,
        "mock": not client.configured,
    }


@router.get("/chat/{session_id}")
async def get_chat(session_id: str, request: Request, _user=Depends(require_auth)):
    store = request.app.state.rp.chat_store
    if store is None:
        raise HTTPException(503, "chat disabled")
    sess = store.get(session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    return {
        "ok": True,
        "session_id": sess.session_id,
        "messages": sess.messages,
        "updated_at": sess.updated_at,
    }


@router.delete("/chat/{session_id}")
async def delete_chat(session_id: str, request: Request, _user=Depends(require_auth)):
    store = request.app.state.rp.chat_store
    if store is None:
        raise HTTPException(503, "chat disabled")
    if not store.delete(session_id):
        raise HTTPException(404, "session not found")
    return {"ok": True, "deleted": session_id}
