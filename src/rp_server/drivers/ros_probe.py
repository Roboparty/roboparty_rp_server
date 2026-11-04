# SPDX-License-Identifier: GPL-3.0
"""Best-effort ROS 2 readiness probes used by the policy driver."""

import asyncio
import logging
import shutil

logger = logging.getLogger("rp_server.ros_probe")


async def services(timeout_s: float = 5.0):
    """Return the current service names, or None when ROS is unavailable."""
    if shutil.which("ros2") is None:
        logger.warning("ros2 not found; readiness probe skipped")
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ros2", "service", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.warning("ros2 service list failed to start: %s", exc)
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("ros2 service list timed out")
        return None
    if proc.returncode != 0:
        return None
    return {line.strip() for line in out.decode(errors="replace").splitlines() if line.strip()}


def service_ready_check(name: str, timeout_s: float = 5.0):
    """Build an async check for a service such as ``start_inference``."""

    target = name if name.startswith("/") else "/" + name

    async def check() -> bool:
        current = await services(timeout_s)
        if current is None:
            # Cannot verify readiness without ROS. Reporting success here would
            # claim STATE_RUNNING for a process that may not be accepting
            # control, so fail closed instead.
            logger.error("readiness probe unavailable: ros2 not found")
            return False
        return target in current or target.lstrip("/") in current

    check.__name__ = f"service_ready_check({target})"
    return check
