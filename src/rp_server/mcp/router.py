# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""HTTP MCP tool surface mounted on the same FastAPI app."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth.router import require_auth
from .tools import TOOLS_SPEC, call_tool, tool_is_readonly

router = APIRouter(prefix="/mcp", tags=["mcp"])


class CallBody(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools")
async def list_tools(request: Request):
    cfg = request.app.state.rp.config.get("mcp", {})
    if not cfg.get("enabled", True):
        raise HTTPException(503, "mcp disabled")
    readonly = cfg.get("readonly", True)
    tools = []
    for t in TOOLS_SPEC:
        if readonly and not t.get("readonly", True):
            continue
        tools.append({
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["inputSchema"],
            "readonly": t.get("readonly", True),
        })
    return {"ok": True, "tools": tools}


@router.post("/call")
async def mcp_call(body: CallBody, request: Request, _user=Depends(require_auth)):
    rp = request.app.state.rp
    cfg = rp.config.get("mcp", {})
    if not cfg.get("enabled", True):
        raise HTTPException(503, "mcp disabled")
    if cfg.get("readonly", True) and not tool_is_readonly(body.name):
        raise HTTPException(403, "mcp is readonly; enable mcp.readonly=false for write tools")
    try:
        result = await call_tool(body.name, body.arguments, rp)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "name": body.name, "result": result}
