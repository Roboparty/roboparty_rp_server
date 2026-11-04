# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""robopi-tui JSON-RPC backend adapter tests (no board required)."""

import asyncio
import json

import pytest

from rp_server.transport.tui_backend import TuiBackend, TuiError

SCRIPT = """\
import json, os, sys
req = json.loads(sys.stdin.readline())
method = req["method"]
if method == "tasks.list":
    result = {"tasks": [{"id": "can-check"}], "methods": ["tasks.list"],
              "identity": {"serial": "SN-1", "machineId": "m", "model": "robopi2"}}
elif method == "jobs.start":
    result = {"taskId": req["params"]["taskId"], "jobId": req["params"]["requestId"]}
else:
    result = {"method": method, "params": req.get("params", {})}
result["server"] = os.environ.get("RP_TUI_SERVER")
print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}))
"""

ERROR_SCRIPT = """\
import json, sys
req = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "error": {
    "code": -32003, "message": "denied", "data": {"code": "PERMISSION_DENIED"}}}))
"""


def backend(tmp_path, body=SCRIPT, **cfg):
    exe = tmp_path / "robopi-tui"
    exe.write_text("#!/usr/bin/env python3\n" + body)
    exe.chmod(0o755)
    return TuiBackend({"enabled": True, "executable": str(exe), **cfg})


def test_read_only_calls(tmp_path):
    tui = backend(tmp_path)
    assert tui.available
    assert asyncio.run(tui.tasks())["tasks"][0]["id"] == "can-check"
    active = asyncio.run(tui.active_job())
    assert active == {"method": "jobs.active", "params": {}, "server": "rp_server"}


def test_identity_comes_from_tasks_list(tmp_path):
    identity = asyncio.run(backend(tmp_path).identity())
    assert identity["serial"] == "SN-1"
    assert identity["model"] == "robopi2"


def test_jobs_are_gated_by_default(tmp_path):
    tui = backend(tmp_path)
    with pytest.raises(TuiError) as exc:
        asyncio.run(tui.start_job("can-check"))
    assert exc.value.code == "DISABLED"
    with pytest.raises(TuiError) as exc:
        asyncio.run(tui.acknowledge("00000000-0000-0000-0000-000000000000"))
    assert exc.value.code == "DISABLED"


def test_start_job_when_enabled(tmp_path):
    tui = backend(tmp_path, allow_jobs=True)
    result = asyncio.run(tui.start_job("can-check"))
    assert result["taskId"] == "can-check"
    assert len(result["jobId"]) == 36


def test_server_name_is_injected(tmp_path):
    assert asyncio.run(backend(tmp_path).active_job())["server"] == "rp_server"
    assert asyncio.run(backend(tmp_path, server="custom").active_job())["server"] == "custom"


def test_error_is_propagated(tmp_path):
    tui = backend(tmp_path, ERROR_SCRIPT)
    with pytest.raises(TuiError) as exc:
        asyncio.run(tui.snapshot())
    assert exc.value.code == "PERMISSION_DENIED"
    assert str(exc.value) == "denied"


def test_missing_executable_is_unavailable(tmp_path):
    tui = TuiBackend({"enabled": True, "executable": str(tmp_path / "missing")})
    assert not tui.available
    with pytest.raises(TuiError) as exc:
        asyncio.run(tui.tasks())
    assert exc.value.code == "UNAVAILABLE"
