# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

import argparse
import logging
import os

import uvicorn
import yaml

from .transport.ws_server import create_app


def _load_dotenv() -> None:
    """Load KEY=VALUE from repo-root .env into os.environ (no overwrite if set)."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    for path in candidates:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
            logging.getLogger("rp_server").info("loaded env file: %s", path)
        except OSError as exc:
            logging.getLogger("rp_server").warning("failed to load .env: %s", exc)
        break


def _load_config(config_path: str = "") -> dict:
    if not config_path:
        config_path = os.environ.get(
            "RP_ROBOT_CONFIG",
            "/opt/roboparty/share/roboto-inference/config/robot/robot.yaml",
        )
    config: dict = {}
    if os.path.isfile(config_path):
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        logging.getLogger("rp_server").warning(
            "robot config not found: %s (continuing with server.yaml only)", config_path
        )

    server_cfg = os.environ.get(
        "RP_SERVER_CONFIG",
        "/opt/roboparty/share/roboparty-rp-server/config/server.yaml",
    )
    candidates = [
        server_cfg,
        os.path.join(os.path.dirname(config_path), "server.yaml") if config_path else "",
        os.path.join(os.path.dirname(__file__), "..", "..", "config", "server.yaml"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                sc = yaml.safe_load(f)
            if sc:
                config.update(sc)
            break

    if os.environ.get("RP_MOCK", "") in ("1", "true", "TRUE"):
        config.setdefault("server", {})["mock"] = True
    return config


def main():
    parser = argparse.ArgumentParser(description="RoboParty RP Server")
    parser.add_argument("--config", default="", help="path to inference robot.yaml")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--mock", action="store_true", help="run without hardware drivers")
    parser.add_argument(
        "--require-hardware",
        action="store_true",
        help="fail startup unless all configured required hardware is ready",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    _load_dotenv()
    config = _load_config(args.config)
    if args.mock:
        config.setdefault("server", {})["mock"] = True
        os.environ["RP_MOCK"] = "1"
    if args.require_hardware:
        config.setdefault("hardware", {})["fail_startup_if_unavailable"] = True

    host = args.host or os.environ.get("RP_HOST") or config.get("server", {}).get("host", "0.0.0.0")
    port = args.port or int(os.environ.get("RP_PORT") or 0) or config.get("server", {}).get("port", 8765)

    app = create_app(config)
    server = uvicorn.Server(uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=args.log_level,
    ))
    server.run()
    if not server.started:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
