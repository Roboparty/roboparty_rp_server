# SPDX-License-Identifier: GPL-3.0
"""Connection-bound control ownership with independent input freshness."""

import asyncio
import logging
import math
import time

logger = logging.getLogger("rp_server.control")


class ControlError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ControlLease:
    def __init__(self, handler, ttl_s=3.0, input_timeout_s=0.5, now=time.monotonic):
        if not all(math.isfinite(v) and v > 0 for v in (ttl_s, input_timeout_s)):
            raise ValueError("control timeouts must be positive finite seconds")
        self.handler = handler
        self.ttl_s = ttl_s
        self.input_timeout_s = input_timeout_s
        self.now = now
        self.owner = None
        self.deadline = 0.0
        self.last_input = None
        self._lock = asyncio.Lock()
        self.fault = False
        self.stopped = False

    def status(self, status):
        return {"type": "lease", "status": status,
                "ttl_ms": round(self.ttl_s * 1000),
                "input_timeout_ms": round(self.input_timeout_s * 1000)}

    async def _stop(self, reason):
        # Session/watchdog cancellation must not interrupt process termination.
        task = asyncio.create_task(self._perform_stop(reason))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def _perform_stop(self, reason):
        # Keep ownership unavailable until stopping has finished, including failures.
        logger.info("control released: reason=%s", reason, extra={"event_type": "lease"})
        self.owner = None
        self.last_input = None
        errors = []
        try:
            self.handler.joy.reset()
        except Exception as exc:
            errors.append(exc)
        try:
            if self.handler.policy.running:
                stopped = await self.handler.policy.stop()
                if stopped is False:
                    errors.append(RuntimeError("policy process did not stop"))
            elif getattr(self.handler.policy, "failed", False):
                errors.append(RuntimeError("policy process failed without an explicit stop"))
        except Exception as exc:
            errors.append(exc)
        if errors:
            self.fault = True
            logger.error("software stop failed; control blocked: %s", errors, extra={"event_type": "lease"})
            raise ControlError("STOP_FAILED", "software stop failed; operator recovery required")

    async def _expire(self):
        if self.owner is not None and (
            self.now() >= self.deadline or
            (self.last_input is not None and
             self.now() - self.last_input >= self.input_timeout_s)
        ):
            await self._stop("timeout")

    async def expire(self):
        async with self._lock:
            await self._expire()

    async def acquire(self, session, authorize=None):
        async with self._lock:
            await self._expire()
            if authorize:
                authorize()
            if self.fault:
                raise ControlError("STOP_FAILED", "control blocked after stop failure")
            if self.stopped:
                raise ControlError("CONTROL_STOPPED", "software stop latched; send stop clear first")
            if self.owner not in (None, session):
                raise ControlError("CONTROL_BUSY", "another session owns control")
            if self.owner is None:
                self.last_input = None
            self.owner = session
            self.deadline = self.now() + self.ttl_s
            logger.info("control acquired: session=%s ttl_s=%s", str(session)[:8], self.ttl_s,
                    extra={"event_type": "lease"})
            return self.status("acquired")

    async def heartbeat(self, session):
        async with self._lock:
            await self._expire()
            if self.owner == session:
                self.deadline = self.now() + self.ttl_s

    async def release(self, session, reason="release"):
        async with self._lock:
            if self.owner == session:
                await self._stop(reason)
            return self.status("released")

    async def stop(self, latch=False):
        async with self._lock:
            if latch:
                self.stopped = True
            await self._stop("software-stop")

    async def clear_stop(self):
        async with self._lock:
            self.stopped = False
            logger.info("control stop cleared", extra={"event_type": "lease"})
            return self.status("cleared")

    async def dispatch(self, session, env, authorize=None):
        async with self._lock:
            await self._expire()
            if authorize:
                authorize()
            if self.owner != session:
                raise ControlError("LEASE_REQUIRED", "explicit lease.acquire required")
            body = env.WhichOneof("body")
            # Reject non-finite input before touching the device or freshness clock.
            values = ([axis.value for axis in env.control.axes] if body == "control"
                      else [env.joystick.value] if body == "joystick" else [])
            if not all(math.isfinite(value) for value in values):
                raise ControlError("INVALID_INPUT", "control values must be finite")
            result = await self.handler.handle(env)
            self.deadline = self.now() + self.ttl_s
            if body in ("control", "joystick", "button"):
                self.last_input = self.now()
            return result
