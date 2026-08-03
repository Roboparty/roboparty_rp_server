#!/usr/bin/env python3
"""Validate production hardware dependencies without moving any motors."""

from __future__ import annotations

import argparse
import importlib
import os
import sys

import yaml


MODULE_BY_DEVICE = {"motors": "motors_py", "imu": "imu_py", "bms": "bms_py"}
DEFAULT_REQUIRED = ("motors", "imu", "bms")


def _load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="real inference robot.yaml")
    parser.add_argument("--server-config", help="rp_server server.yaml merged after robot config")
    args = parser.parse_args()

    errors: list[str] = []
    config: dict = {}

    if not os.path.isfile(args.config):
        errors.append(f"robot config not found: {args.config}")
    else:
        config = _load_yaml(args.config)
    if args.server_config:
        if not os.path.isfile(args.server_config):
            errors.append(f"server config not found: {args.server_config}")
        else:
            config.update(_load_yaml(args.server_config))

    required = config.get("hardware", {}).get("required") or list(DEFAULT_REQUIRED)
    unknown = [dev for dev in required if dev not in MODULE_BY_DEVICE]
    if unknown:
        errors.append(f"hardware.required lists unknown devices: {', '.join(unknown)}")
    print("required hardware: " + ", ".join(required))

    for device, module in MODULE_BY_DEVICE.items():
        try:
            importlib.import_module(module)
        except Exception as exc:
            if device in required:
                errors.append(f"module {module}: {exc}")
            else:
                print(f"SKIP module {module} (device {device} not required): {exc}")
        else:
            print(f"OK module {module}")

    if config:
        motor_ids = config.get("motors", {}).get("motor_id", [])
        if not motor_ids:
            (errors.append if "motors" in required else print)(
                "robot config has no motors.motor_id entries"
            )
        else:
            print(f"OK motor config ({len(motor_ids)} ids)")

        imu_config = config.get("imu", {})
        if not imu_config:
            (errors.append if "imu" in required else print)("robot config has no imu section")
        else:
            imu_interface = imu_config.get(
                "imu_interface",
                imu_config.get("interface", "unspecified"),
            )
            print(f"OK imu config ({imu_interface})")

        bms_config = config.get("bms", {})
        if not bms_config:
            (errors.append if "bms" in required else print)("robot config has no bms section")
        else:
            print(f"OK bms config ({bms_config.get('socket_path', 'unspecified')})")

    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1

    print("HARDWARE_PREFLIGHT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
