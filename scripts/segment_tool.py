#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""List, package and upload inference telemetry segments.

Examples:
    python3 scripts/segment_tool.py list
    python3 scripts/segment_tool.py package --session <id> --output /tmp/seg.tar.gz
    python3 scripts/segment_tool.py upload --session <id> --device-id rp1 \
        --url http://127.0.0.1:8092 --yes
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = Path(os.environ.get("RP_LOG_DIR", ROOT / "logs")) / "segments"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def segment_dir(base: Path, session: str) -> Path:
    path = base / session
    if not path.is_dir():
        raise SystemExit(f"segment not found: {path}")
    return path


def make_package(base: Path, session: str, output: Path,
                 policy_log: Path | None = None) -> Path:
    source = segment_dir(base, session)
    meta = json.loads((source / "meta.json").read_text(encoding="utf-8"))
    files = []
    for name in ("meta.json", "events.jsonl", "telemetry.jsonl"):
        path = source / name
        if path.is_file():
            files.append(path)
    if policy_log is not None:
        if not policy_log.is_file():
            raise SystemExit(f"policy log not found: {policy_log}")
        files.append(policy_log)

    manifest = {
        "schema_version": "1",
        "inference_session_id": session,
        "created_at": now(),
        "segment": meta,
        "files": {
            (("policy.log" if path == policy_log else path.name)): {
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="segment-package-") as tmp:
        manifest_path = Path(tmp) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        with tarfile.open(output, "w:gz") as archive:
            archive.add(manifest_path, arcname="manifest.json")
            for path in files:
                arcname = "policy.log" if path == policy_log else path.name
                archive.add(path, arcname=arcname)
    return output


def upload_archive(path: Path, device_id: str, session: str, url: str,
                   token: str, meta: dict | None = None,
                   policy: str = "", software_version: str = "") -> dict:
    data = path.read_bytes()
    headers = {
        "Content-Type": "application/gzip",
        "X-Device-Id": device_id,
        "X-Inference-Session-Id": session,
        "X-Segment-Filename": path.name,
        "X-Segment-Sha256": hashlib.sha256(data).hexdigest(),
        "X-Segment-Policy": policy,
        "X-Software-Version": software_version,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if meta:
        import base64
        headers["X-Segment-Meta"] = base64.b64encode(
            json.dumps(meta, ensure_ascii=False).encode()).decode()
    request = Request(url.rstrip("/") + "/v1/segments", data=data,
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        raise SystemExit(f"upload failed: HTTP {exc.code}: "
                         f"{exc.read().decode('utf-8', 'replace')[:300]}") from exc
    except URLError as exc:
        raise SystemExit(f"upload failed: {exc.reason}") from exc


def cmd_list(args) -> int:
    base = Path(args.dir)
    if not base.is_dir():
        print(f"no segments directory: {base}")
        return 1
    rows = []
    for directory in sorted(base.iterdir()):
        meta_path = directory / "meta.json"
        if not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rows.append((meta.get("inference_session_id", directory.name),
                     meta.get("policy", ""), meta.get("phase", ""),
                     meta.get("samples", 0), meta.get("started_at", "")))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        print(f"{'session':34} {'policy':16} {'phase':10} {'samples':>8}  started_at")
        for row in rows:
            print(f"{row[0]:34} {row[1]:16} {row[2]:10} {row[3]:>8}  {row[4]}")
    return 0


def cmd_show(args) -> int:
    directory = segment_dir(Path(args.dir), args.session)
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    files = {path.name: {"size": path.stat().st_size, "sha256": sha256(path)}
             for path in sorted(directory.iterdir())
             if path.is_file() and path.name != "meta.json"}
    print(json.dumps({"meta": meta, "files": files}, ensure_ascii=False, indent=2))
    return 0


def cmd_package(args) -> int:
    output = Path(args.output) if args.output else (
        Path(args.dir) / "exports" / f"{args.session}.tar.gz")
    policy_log = Path(args.policy_log) if args.policy_log else None
    path = make_package(Path(args.dir), args.session, output, policy_log)
    print(path)
    return 0


def cmd_upload(args) -> int:
    meta = {}
    if args.policy_log:
        meta["policy_log"] = args.policy_log
    if not args.yes:
        print("upload requires explicit consent; re-run with --yes after reviewing the segment")
        return 2
    output = Path(args.output) if args.output else (
        Path(args.dir) / "exports" / f"{args.session}.tar.gz")
    path = make_package(Path(args.dir), args.session, output,
                        Path(args.policy_log) if args.policy_log else None)
    segment_meta = json.loads((Path(args.dir) / args.session / "meta.json")
                              .read_text(encoding="utf-8"))
    result = upload_archive(
        path, args.device_id, args.session, args.url, args.token, meta,
        policy=str(segment_meta.get("policy", "")),
        software_version=str(segment_meta.get("rp_server_version", "")),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_upload_file(args) -> int:
    if not args.yes:
        print("upload requires explicit consent; re-run with --yes after reviewing the archive")
        return 2
    result = upload_archive(Path(args.file), args.device_id, args.session_id,
                            args.url, args.token,
                            policy=args.policy, software_version=args.software_version)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=str(DEFAULT_DIR),
                        help="segment directory (default: <RP_LOG_DIR>/segments)")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list local segments")
    listing.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="show a segment without uploading")
    show.add_argument("--session", required=True)

    package = sub.add_parser("package", help="package a segment as tar.gz")
    package.add_argument("--session", required=True)
    package.add_argument("--output", default="")
    package.add_argument("--policy-log", default="")

    upload = sub.add_parser("upload", help="package and upload with consent")
    upload.add_argument("--session", required=True)
    upload.add_argument("--device-id", required=True)
    upload.add_argument("--url", default=os.environ.get("RP_LOG_SERVER_URL",
                                                        "http://127.0.0.1:8092"))
    upload.add_argument("--token", default=os.environ.get("RP_LOG_TOKEN", ""))
    upload.add_argument("--output", default="")
    upload.add_argument("--policy-log", default="")
    upload.add_argument("--yes", action="store_true")

    upload_file = sub.add_parser("upload-file", help="upload an existing archive with consent")
    upload_file.add_argument("--file", required=True)
    upload_file.add_argument("--session-id", required=True)
    upload_file.add_argument("--device-id", required=True)
    upload_file.add_argument("--url", default=os.environ.get("RP_LOG_SERVER_URL",
                                                             "http://127.0.0.1:8092"))
    upload_file.add_argument("--token", default=os.environ.get("RP_LOG_TOKEN", ""))
    upload_file.add_argument("--policy", default="")
    upload_file.add_argument("--software-version", default="")
    upload_file.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    command = {
        "list": cmd_list,
        "show": cmd_show,
        "package": cmd_package,
        "upload": cmd_upload,
        "upload-file": cmd_upload_file,
    }[args.command]
    return command(args)


if __name__ == "__main__":
    raise SystemExit(main())
