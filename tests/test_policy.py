# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""PolicyDriver tests: stop must reap the whole process group."""

import asyncio
import os
import shlex
import time

import pytest

from rp_server.drivers.policy import PolicyDriver


def test_stop_kills_launch_children(tmp_path):
    pidfile = tmp_path / "child.pid"
    cmd = "bash -c 'sleep 30 & echo $! > {}; wait'".format(
        shlex.quote(str(pidfile))
    )
    driver = PolicyDriver(cmd)

    async def scenario():
        assert await driver.start("test") is True
        for _ in range(200):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            await asyncio.sleep(0.01)
        child = int(pidfile.read_text().strip())
        await driver.stop()
        return child

    child = asyncio.run(scenario())

    for _ in range(100):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        else:
            time.sleep(0.01)
    else:
        pytest.fail(f"child process {child} survived policy.stop()")

    assert driver.running is False
    assert driver.name == ""


def test_start_fails_when_readiness_never_arrives():
    driver = PolicyDriver("sleep 30", ready_check=lambda: _false(), ready_timeout_s=0.2)

    async def scenario():
        return await driver.start("test")

    assert asyncio.run(scenario()) is False
    assert driver.running is False
    assert driver.failed is True
    assert driver.state == "FAIL"


async def _false():
    return False


def test_unexpected_exit_is_reported_as_fail():
    driver = PolicyDriver("sleep 0.05")

    async def scenario():
        assert await driver.start("test") is True
        for _ in range(100):
            if driver.running is False:
                break
            await asyncio.sleep(0.01)
        return driver.state

    assert asyncio.run(scenario()) == "FAIL"
    assert driver.failed is True


def test_stop_confirms_exit_and_reports_stopped():
    driver = PolicyDriver("sleep 30")

    async def scenario():
        assert await driver.start("test") is True
        return await driver.stop()

    assert asyncio.run(scenario()) is True
    assert driver.running is False
    assert driver.state == "STOPPED"


def test_developer_mode_bypasses_control_lock(tmp_path):
    import fcntl

    lock = tmp_path / "control.lock"
    marker = tmp_path / "env.txt"
    fd = lock.open("a+")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    command = "bash -c 'echo \"$ROBOPARTY_CONTROL_LOCK_HELD\" > {}; sleep 30'".format(
        shlex.quote(str(marker))
    )
    driver = PolicyDriver(command, lock_path=str(lock), developer_mode=True)
    try:
        async def scenario():
            assert await driver.start("test") is True
            for _ in range(200):
                if marker.exists() and marker.read_text().strip():
                    break
                await asyncio.sleep(0.01)
            value = marker.read_text().strip()
            await driver.stop()
            return value

        assert asyncio.run(scenario()) == "1"
        assert driver.developer_mode is True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def test_start_fails_when_control_lock_is_busy(tmp_path):
    import fcntl

    lock = tmp_path / "control.lock"
    fd = lock.open("a+")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        driver = PolicyDriver("sleep 30", lock_path=str(lock))
        assert asyncio.run(driver.start("test")) is False
        assert driver.state == "FAIL"
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def test_repeated_start_reports_existing_instance_without_killing_it():
    driver = PolicyDriver("sleep 30", instance_check=lambda: True)

    async def scenario():
        return await driver.start("test")

    assert asyncio.run(scenario()) is False
    assert driver.failed is True
    assert driver.state == "FAIL"
    assert driver.running is False
