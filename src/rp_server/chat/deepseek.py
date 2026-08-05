# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""OpenAI-compatible chat client — RoboParty AI Gateway / DeepSeek."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("rp_server.chat.deepseek")

# Official DeepSeek API (OpenAI-compatible). RoboParty gateway also works if api_base is set accordingly.
DEFAULT_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        api_base: str = DEFAULT_API_BASE,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _completions_url(self) -> str:
        base = self.api_base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise RuntimeError("API key not configured (RP_DEEPSEEK_API_KEY / .env)")
        url = self._completions_url()
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data: dict[str, Any] = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            logger.error("LLM HTTP %s url=%s: %s", exc.code, url, detail)
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM network error: {exc}") from exc

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"unexpected LLM response: {data}") from exc
