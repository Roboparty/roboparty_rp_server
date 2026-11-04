"""Offline ownership tests; no drivers or real clocks are involved."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from rp_server.protocol.codec import Envelope
from rp_server.protocol.control_lease import ControlError, ControlLease


def setup():
    clock = [10.0]
    handler = SimpleNamespace(joy=SimpleNamespace(reset=Mock()),
                              policy=SimpleNamespace(running=True, stop=AsyncMock()),
                              handle=AsyncMock(return_value=[]))
    lease = ControlLease(handler, now=lambda: clock[0])
    env = Envelope()
    env.control.axes.add(axis=1, value=0.5)
    return lease, handler, clock, env


def test_exclusive_and_disconnect_never_clears_motor_errors():
    async def run():
        lease, handler, _, env = setup()
        await lease.acquire("a")
        with pytest.raises(ControlError, match="another session"):
            await lease.acquire("b")
        await lease.dispatch("a", env)
        await lease.release("b")
        handler.joy.reset.assert_not_called()
        await lease.release("a", "disconnect")
        handler.joy.reset.assert_called_once()
        handler.policy.stop.assert_awaited_once()
        with pytest.raises(ControlError, match="lease.acquire"):
            await lease.dispatch("reconnected-a", env)
    asyncio.run(run())


def test_heartbeat_does_not_refresh_input_and_expired_owner_must_reacquire():
    async def run():
        lease, handler, clock, env = setup()
        await lease.acquire("a")
        await lease.dispatch("a", env)
        clock[0] += 0.4
        await lease.heartbeat("a")
        clock[0] += 0.11
        await lease.expire()
        assert lease.owner is None
        with pytest.raises(ControlError):
            await lease.dispatch("a", env)
        assert handler.handle.await_count == 1
        await lease.acquire("a")
        await lease.dispatch("a", env)
    asyncio.run(run())


def test_lease_without_input_expires_and_new_owner_waits_for_stop():
    async def run():
        lease, handler, clock, _ = setup()
        entered, finish = asyncio.Event(), asyncio.Event()
        async def stop():
            entered.set()
            await finish.wait()
        handler.policy.stop.side_effect = stop
        await lease.acquire("a")
        clock[0] += 4
        expiry = asyncio.create_task(lease.expire())
        await entered.wait()
        acquire = asyncio.create_task(lease.acquire("b"))
        await asyncio.sleep(0)
        assert not acquire.done()
        finish.set()
        await expiry
        await acquire
        assert lease.owner == "b"
    asyncio.run(run())


def test_stop_failure_latches_and_nonfinite_input_is_rejected():
    async def run():
        lease, handler, _, env = setup()
        await lease.acquire("a")
        env.control.axes[0].value = float("nan")
        with pytest.raises(ControlError, match="finite"):
            await lease.dispatch("a", env)
        handler.handle.assert_not_awaited()
        handler.policy.stop.side_effect = RuntimeError("failed")
        with pytest.raises(ControlError, match="stop failed"):
            await lease.release("a")
        with pytest.raises(ControlError, match="blocked"):
            await lease.acquire("b")
    asyncio.run(run())


def test_cancelled_watchdog_finishes_stop_before_new_acquisition():
    async def run():
        lease, handler, clock, _ = setup()
        entered, finish = asyncio.Event(), asyncio.Event()
        async def stop():
            entered.set()
            await finish.wait()
        handler.policy.stop.side_effect = stop
        await lease.acquire("a")
        clock[0] += 4
        expiry = asyncio.create_task(lease.expire())
        await entered.wait()
        expiry.cancel()
        acquire = asyncio.create_task(lease.acquire("b"))
        await asyncio.sleep(0)
        assert not acquire.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await expiry
        await acquire
        assert lease.owner == "b"
    asyncio.run(run())


def test_explicit_stop_latches_until_cleared():
    async def run():
        lease, _, _, _ = setup()
        await lease.acquire("a")
        await lease.stop(latch=True)
        assert lease.stopped
        with pytest.raises(ControlError, match="latched"):
            await lease.acquire("a")
        await lease.clear_stop()
        await lease.acquire("a")
        assert lease.owner == "a"
    asyncio.run(run())


def test_release_latches_when_policy_stop_is_not_confirmed():
    async def run():
        lease, handler, _, _ = setup()
        handler.policy.stop.return_value = False
        await lease.acquire("a")
        with pytest.raises(ControlError, match="stop failed"):
            await lease.release("a")
        assert lease.fault is True
    asyncio.run(run())
