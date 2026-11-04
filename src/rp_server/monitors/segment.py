# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Inference-scoped telemetry segment recorder.

One segment corresponds to one policy/inference node start-to-stop. Telemetry
samples are kept in a short in-memory pre-window; while a segment is active they
are written to ``<dir>/<inference_session_id>/telemetry.jsonl``. The recorder
also keeps writing for ``post_window_s`` after stop so shutdown evidence is not
lost. It never uploads anything.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import queue
import threading
import time

from .. import __version__
from ..transport.json_gateway import telemetry_json

logger = logging.getLogger("rp_server.segment")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class SegmentRecorder:
    def __init__(self, directory: str, pre_window_s: float = 5.0,
                 post_window_s: float = 5.0, buffer_s: float = 10.0,
                 queue_size: int = 4096, enabled: bool = True):
        self.dir = Path(directory)
        self.pre_window_s = max(0.0, float(pre_window_s))
        self.post_window_s = max(0.0, float(post_window_s))
        self.buffer_s = max(self.pre_window_s, float(buffer_s))
        self.enabled = bool(enabled)
        self.dropped = 0
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self._stopped = threading.Event()
        self._thread = None
        if self.enabled:
            self._thread = threading.Thread(target=self._run, name="rp-segment", daemon=True)
            self._thread.start()

    def record(self, envelope) -> None:
        if not self.enabled:
            return
        payload = telemetry_json(envelope)
        if payload is not None:
            self._put(("sample", time.monotonic(), payload))

    def on_lifecycle(self, phase: str, session_id: str, policy: str, extra: dict) -> None:
        if not self.enabled:
            return
        self._put(("lifecycle", time.monotonic(),
                   {"phase": phase, "session_id": session_id,
                    "policy": policy, "extra": extra}))

    def _put(self, item) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        buffer: deque = deque()
        active = None
        while True:
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                item = None
            now = time.monotonic()
            if item is not None:
                kind, stamp, data = item
                if kind == "lifecycle":
                    active = self._on_lifecycle(active, stamp, data, buffer)
                else:
                    buffer.append((stamp, data))
                    cutoff = stamp - self.buffer_s
                    while buffer and buffer[0][0] < cutoff:
                        buffer.popleft()
                    if active is not None:
                        self._write_sample(active, stamp, data)
            if active is not None and active.get("closing_until") is not None:
                if now >= active["closing_until"]:
                    self._close_segment(active)
                    active = None
            if self._stopped.is_set() and self._queue.empty():
                if active is not None:
                    self._close_segment(active)
                return

    def _on_lifecycle(self, active, stamp, data, buffer):
        phase = data["phase"]
        session_id = data["session_id"]
        policy = data["policy"]
        if phase == "starting":
            if active is not None:
                self._close_segment(active, reason="superseded")
            active = self._open_segment(session_id, policy, data["extra"])
            self._write_event(active, stamp, data)
            cutoff = stamp - self.pre_window_s
            for sample_stamp, payload in buffer:
                if sample_stamp >= cutoff:
                    self._write_sample(active, sample_stamp, payload)
            return active
        if active is None or active["session_id"] != session_id:
            return active
        if phase == "running":
            active["phase"] = "running"
            active["running_at"] = _iso_now()
        elif phase == "stopping":
            active["phase"] = "stopping"
            active["stopping_at"] = _iso_now()
            active["closing_until"] = stamp + self.post_window_s
        elif phase in ("stopped", "failed"):
            active["phase"] = phase
            active["stopped_at"] = _iso_now()
            active["stop_extra"] = data["extra"]
            active["closing_until"] = stamp + self.post_window_s
        self._write_event(active, stamp, data)
        self._write_meta(active)
        return active

    def _open_segment(self, session_id: str, policy: str, extra: dict) -> dict:
        directory = self.dir / session_id
        directory.mkdir(parents=True, exist_ok=True)
        telemetry = open(directory / "telemetry.jsonl", "a", encoding="utf-8")
        events = open(directory / "events.jsonl", "a", encoding="utf-8")
        active = {
            "session_id": session_id,
            "policy": policy,
            "dir": directory,
            "telemetry": telemetry,
            "events": events,
            "started_at": _iso_now(),
            "phase": "starting",
            "running_at": "",
            "stopping_at": "",
            "stopped_at": "",
            "closing_until": None,
            "samples": 0,
            "start_extra": dict(extra or {}),
            "stop_extra": {},
        }
        self._write_meta(active)
        return active

    def _write_event(self, active: dict, stamp: float, data: dict) -> None:
        record = {
            "inference_session_id": active["session_id"],
            "phase": data["phase"],
            "policy": data["policy"],
            "timestamp": _iso_now(),
            "extra": data.get("extra", {}),
        }
        active["events"].write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_sample(self, active: dict, stamp: float, payload: dict) -> None:
        record = dict(payload)
        record["inference_session_id"] = active["session_id"]
        record["recorded_at"] = _iso_now()
        active["telemetry"].write(json.dumps(record, ensure_ascii=False) + "\n")
        active["samples"] += 1

    def _write_meta(self, active: dict) -> None:
        meta = {
            "schema_version": "1",
            "inference_session_id": active["session_id"],
            "policy": active["policy"],
            "phase": active["phase"],
            "started_at": active["started_at"],
            "running_at": active["running_at"],
            "stopping_at": active["stopping_at"],
            "stopped_at": active["stopped_at"],
            "samples": active["samples"],
            "rp_server_version": __version__,
            "dropped": self.dropped,
            "start": active["start_extra"],
            "stop": active["stop_extra"],
        }
        path = active["dir"] / "meta.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def _close_segment(self, active: dict, reason: str = "") -> None:
        active["stopped_at"] = active["stopped_at"] or _iso_now()
        if reason:
            active["stop_extra"].setdefault("reason", reason)
        self._write_meta(active)
        for key in ("telemetry", "events"):
            try:
                active[key].close()
            except OSError:
                pass

    def close(self) -> None:
        if not self.enabled:
            return
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
