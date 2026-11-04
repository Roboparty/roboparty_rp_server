# SPDX-License-Identifier: GPL-3.0
"""Readiness probes must fail closed when ROS cannot be queried."""

import asyncio

from rp_server.drivers import ros_probe


def test_readiness_fails_closed_without_ros(monkeypatch):
    async def no_ros(timeout_s=5.0):
        return None

    monkeypatch.setattr(ros_probe, "services", no_ros)
    check = ros_probe.service_ready_check("start_inference")
    assert asyncio.run(check()) is False


def test_readiness_checks_service_name(monkeypatch):
    async def fake_services(timeout_s=5.0):
        return {"/start_inference"}

    monkeypatch.setattr(ros_probe, "services", fake_services)
    check = ros_probe.service_ready_check("start_inference")
    assert asyncio.run(check()) is True

    missing = ros_probe.service_ready_check("not_running")
    assert asyncio.run(missing()) is False
