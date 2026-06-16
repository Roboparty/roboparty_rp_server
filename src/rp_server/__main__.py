# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 wentywenty

import argparse
import logging
import os

import uvicorn
import yaml

from .transport.ws_server import create_app


def _load_config(config_path: str = "") -> dict:
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
    for path in (server_cfg, os.path.join(os.path.dirname(config_path), "server.yaml")):
        if os.path.isfile(path):
            with open(path) as f:
                sc = yaml.safe_load(f)
            if sc:
                config.update(sc)
            break
    return config


def main():
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

    app = create_app(config)
    uvicorn.run(app, host=host, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
