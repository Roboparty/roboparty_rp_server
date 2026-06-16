# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

"""FastAPI application entry point for RoboParty RP Server."""

import asyncio
import logging
import os
import subprocess
import sys

import psutil
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .at_parser import (
    AtCommand, CmdType,
    resp_conn, resp_btn, resp_sysinfo, resp_policy, resp_err,
)
from .joy_bridge import JoyBridge
from .monitors import TelemetryMonitor
from .robot import RobotManager

logger = logging.getLogger("rp_server")


def _load_config(config_path: str = "") -> dict:
    """Load inference robot.yaml, then merge server.yaml."""
    # robot config: reuse inference's robot.yaml
    if not config_path:
        config_path = os.environ.get(
            "RP_ROBOT_CONFIG",
            "/opt/roboparty/share/roboparty-inference/config/robot/robot.yaml",
        )
    with open(config_path) as f:
        config = yaml.safe_load(f)

    server_cfg = os.environ.get(
        "RP_SERVER_CONFIG",
        "/opt/roboparty/share/roboparty-rp-server/config/server.yaml",
    )
    # Also check next to robot.yaml
    if not os.path.isfile(server_cfg):
        server_cfg = os.path.join(os.path.dirname(config_path), "server.yaml")
    server_cfg2 = os.path.join(os.path.dirname(config_path), "server.yaml")

    for path in (server_cfg, server_cfg2):
        if os.path.isfile(path):
            with open(path) as f:
                sc = yaml.safe_load(f)
            if sc:
                config.update(sc)
            break
    return config


def create_app(config_path: str = "") -> FastAPI:
    app = FastAPI(title="RoboParty RP Server", version="1.0.0")

    # --- config ---
    config = _load_config(config_path)

    # --- components ---
    robot = RobotManager(config)
    telemetry = TelemetryMonitor(robot, config)
    joy = JoyBridge()

    # policy state
    policy_proc: subprocess.Popen | None = None
    policy_name: str = ""
    policy_check_task: asyncio.Task | None = None

    async def _policy_monitor():
        """Background task: watch inference_node process and update state."""
        nonlocal policy_proc, policy_name
        while True:
            await asyncio.sleep(1.0)
            if policy_proc is not None:
                rc = policy_proc.poll()
                if rc is not None:
                    logger.warning("policy process exited with code %d", rc)
                    policy_proc = None
                    policy_name = ""

    async def _start_policy(name: str) -> bool:
        nonlocal policy_proc, policy_name
        if policy_proc is not None:
            logger.warning("policy already running")
            return False
        try:
            cmd = config.get("robot", {}).get(
                "launch_cmd",
                "ros2 launch roboparty-inference inference.launch.py",
            )
            env = os.environ.copy()
            # source ROS 2 if available
            ros_setup = "/opt/ros/humble/setup.bash"
            roboparty_setup = "/opt/roboparty/setup.bash"
            if os.path.isfile(ros_setup):
                env["AMENT_PREFIX_PATH"] = env.get("AMENT_PREFIX_PATH", "/opt/ros/humble")
            policy_proc = subprocess.Popen(
                cmd, shell=True, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            policy_name = name
            logger.info("policy started: %s (pid %d)", name, policy_proc.pid)
            return True
        except Exception as exc:
            logger.error("policy start failed: %s", exc)
            return False

    async def _stop_policy():
        nonlocal policy_proc, policy_name
        if policy_proc is None:
            return
        try:
            policy_proc.terminate()
            try:
                policy_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                policy_proc.kill()
                policy_proc.wait()
        except Exception as exc:
            logger.warning("policy stop error: %s", exc)
        policy_proc = None
        policy_name = ""

    def _policy_running() -> bool:
        return policy_proc is not None and policy_proc.poll() is None

    def _policy_name_str() -> str:
        return policy_name

    # --- lifespan ---
    @app.on_event("startup")
    async def on_startup():
        robot.init_all()
        joy.connect()
        await telemetry.start()

    @app.on_event("shutdown")
    async def on_shutdown():
        await telemetry.stop()
        if _policy_running():
            await _stop_policy()
        joy.disconnect()
        robot.deinit_all()

    # ------------------------------------------------------------------
    # REST endpoints
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health():
        return {"status": "ok", "hw_ready": robot.hardware_ready}

    @app.get("/sysinfo")
    async def sysinfo():
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        return {"cpu": cpu, "mem": mem}

    @app.get("/api/status")
    async def api_status():
        errors = robot.get_motor_errors()
        bms = robot.read_bms()
        imu = robot.read_imu()
        return JSONResponse({
            "hw_ready": robot.hardware_ready,
            "policy": _policy_name_str(),
            "policy_running": _policy_running(),
            "joy_device": joy.device_path,
            "motor_errors": errors,
            "battery": bms,
            "imu": imu,
        })

    # ------------------------------------------------------------------
    # WebSocket — AT protocol
    # ------------------------------------------------------------------

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        if policy_check_task is None:
            policy_task = asyncio.create_task(_policy_monitor())

        await ws.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        telemetry.add_client(q)

        async def sender():
            while True:
                msg = await q.get()
                try:
                    await ws.send_text(msg)
                except Exception:
                    break

        send_task = asyncio.create_task(sender())

        try:
            await ws.send_text(resp_conn(True, robot.hardware_ready))

            async for raw in ws.iter_text():
                cmd = AtCommand.parse(raw)
                if cmd is None:
                    continue
                try:
                    await _handle_at_command(ws, cmd, robot, config, joy,
                                             _start_policy, _stop_policy,
                                             _policy_running, _policy_name_str)
                except Exception as exc:
                    logger.warning("AT handler error: %s", exc)
        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()
            telemetry.remove_client(q)

    return app


# ------------------------------------------------------------------
# AT command dispatch
# ------------------------------------------------------------------

async def _handle_at_command(ws: WebSocket, cmd: AtCommand,
                              robot: RobotManager, config: dict,
                              joy: JoyBridge,
                              start_policy_fn, stop_policy_fn,
                              policy_running_fn, policy_name_fn):
    if cmd.cmd == CmdType.CONN_QUERY:
        await ws.send_text(resp_conn(True, robot.hardware_ready))

    elif cmd.cmd == CmdType.SYSINFO_QUERY:
        cpu = psutil.cpu_percent(interval=0.05)
        mem = psutil.virtual_memory().percent
        load = ",".join(f"{x:.2f}" for x in psutil.getloadavg())
        await ws.send_text(resp_sysinfo(cpu, mem, f"load={load}"))

    elif cmd.cmd == CmdType.BTN:
        name, state, cid = cmd.args[0], cmd.args[1], cmd.args[2]
        joy.set_button(name, state)
        await ws.send_text(resp_btn(cid, "OK", cmd.ts))

    elif cmd.cmd == CmdType.JOY:
        axis, val = cmd.args[0], float(cmd.args[1])
        joy.set_axis(axis, val)

    elif cmd.cmd == CmdType.POLICY_QUERY:
        state = "RUNNING" if policy_running_fn() else "STOPPED"
        await ws.send_text(resp_policy(policy_name_fn() or "none", state))

    elif cmd.cmd == CmdType.POLICY_CMD:
        name, action = cmd.args[0], cmd.args[1]
        if action == "start":
            ok = await start_policy_fn(name)
            await ws.send_text(resp_policy(name, "RUNNING" if ok else "FAIL"))
        elif action == "stop":
            await stop_policy_fn()
            await ws.send_text(resp_policy(name, "STOPPED"))

    elif cmd.cmd == CmdType.ERR_QUERY:
        errors = robot.get_motor_errors()
        if not errors:
            await ws.send_text("+ERR: none")
        else:
            for e in errors:
                await ws.send_text(resp_err(e["id"], e["code"], e["name"]))


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="RoboParty RP Server")
    parser.add_argument("--config", default="", help="path to inference robot.yaml")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    config = _load_config(args.config)

    host = args.host or config.get("server", {}).get("host", "0.0.0.0")
    port = args.port or config.get("server", {}).get("port", 8765)

    app = create_app(args.config)
    uvicorn.run(app, host=host, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
