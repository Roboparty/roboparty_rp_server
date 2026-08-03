# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""Chat session store — multi-turn history keyed by session_id."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatSession:
    session_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ChatStore:
    def __init__(self, max_history: int = 20):
        self.max_history = max_history
        self._sessions: dict[str, ChatSession] = {}

    def get_or_create(self, session_id: str | None = None) -> ChatSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        sid = session_id or uuid.uuid4().hex
        sess = ChatSession(session_id=sid)
        self._sessions[sid] = sess
        return sess

    def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def append(self, session: ChatSession, role: str, content: str):
        session.messages.append({"role": role, "content": content})
        # keep system + last N turns
        if len(session.messages) > self.max_history + 1:
            system = [m for m in session.messages if m["role"] == "system"][:1]
            rest = [m for m in session.messages if m["role"] != "system"]
            session.messages = system + rest[-(self.max_history):]
        session.updated_at = time.time()

    def as_openai_messages(self, session: ChatSession) -> list[dict[str, str]]:
        return list(session.messages)
