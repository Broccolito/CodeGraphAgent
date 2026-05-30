"""proxy.py — intercepting MCP proxy with synthetic index_project tool."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from codegraphagent import proxy


REPO_ROOT = Path(__file__).resolve().parent.parent
FAKE_ENGINE_ARGV = ["-m", "tests.fixtures.fake_engine"]


def _send(buf: io.BytesIO, frame: dict) -> None:
    buf.write((json.dumps(frame) + "\n").encode())


def _parse_frames(buf: io.BytesIO) -> list[dict]:
    return [json.loads(l) for l in buf.getvalue().decode().splitlines() if l.strip()]


def _run_proxy(parent_in: io.BytesIO, parent_out: io.BytesIO, tmp_path: Path) -> int:
    parent_in.seek(0)
    return proxy.run(
        launcher=Path(sys.executable),
        cwd=tmp_path,
        argv_override=FAKE_ENGINE_ARGV,
        env_override={"PYTHONPATH": str(REPO_ROOT)},
        stdin=parent_in,
        stdout=parent_out,
        stderr=sys.stderr.buffer,
    )


def test_passthrough_initialize(tmp_path: Path):
    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2024-11-05",
                                 "capabilities": {}, "clientInfo": {}}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 99, "method": "shutdown"})

    parent_out = io.BytesIO()
    rc = _run_proxy(parent_in, parent_out, tmp_path)

    assert rc == 0
    frames = _parse_frames(parent_out)
    # Both initialize and shutdown should have responses
    by_id = {f.get("id"): f for f in frames if "id" in f}
    assert 1 in by_id
    assert by_id[1]["result"]["serverInfo"]["name"] == "fake-engine"


def test_tools_list_response_has_index_project_appended(tmp_path: Path):
    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    _send(parent_in, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})

    parent_out = io.BytesIO()
    rc = _run_proxy(parent_in, parent_out, tmp_path)
    assert rc == 0

    frames = _parse_frames(parent_out)
    tools_list = next(f for f in frames if f.get("id") == 2)
    names = [t["name"] for t in tools_list["result"]["tools"]]
    assert "codegraphagent_index_project" in names
    # And the engine's tools survive too.
    assert "codegraph_search" in names


def test_tools_call_codegraph_search_passes_through_to_engine(tmp_path: Path):
    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "codegraph_search",
                                 "arguments": {"query": "hello"}}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})

    parent_out = io.BytesIO()
    rc = _run_proxy(parent_in, parent_out, tmp_path)
    assert rc == 0

    frames = _parse_frames(parent_out)
    search_resp = next(f for f in frames if f.get("id") == 2)
    text = search_resp["result"]["content"][0]["text"]
    assert "FAKE search result" in text and "hello" in text


def test_tools_call_index_project_invokes_launcher_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When the agent calls codegraphagent_index_project, the proxy shells
    out to <launcher> init (or index --force) against cwd, captures the
    output, and returns it as a tool result. Engine is NOT involved."""
    fake_subprocess_run_calls = []

    class FakeCompleted:
        def __init__(self, rc, stdout, stderr):
            self.returncode = rc
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        fake_subprocess_run_calls.append((cmd, kwargs))
        return FakeCompleted(0, b"Indexed 3 files, 10 nodes.\n", b"")

    monkeypatch.setattr(proxy.subprocess, "run", fake_run)

    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "codegraphagent_index_project",
                                 "arguments": {}}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})

    parent_out = io.BytesIO()
    rc = _run_proxy(parent_in, parent_out, tmp_path)
    assert rc == 0

    # Exactly one subprocess.run call, against a launcher with init or index.
    assert len(fake_subprocess_run_calls) == 1
    cmd, kwargs = fake_subprocess_run_calls[0]
    assert cmd[0] == sys.executable  # launcher (Python in tests)
    assert cmd[1] in ("init", "index")
    assert kwargs.get("cwd") == str(tmp_path)

    # Proxy returned a non-error tool result with the captured stdout.
    frames = _parse_frames(parent_out)
    index_resp = next(f for f in frames if f.get("id") == 2)
    assert index_resp["result"]["isError"] is False
    text = index_resp["result"]["content"][0]["text"]
    assert "Indexing complete" in text
    assert "Indexed 3 files" in text


def test_tools_call_index_project_picks_index_force_when_db_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If .codegraph/codegraph.db exists, use `index --force` (re-index) not `init`."""
    db_path = tmp_path / ".codegraph" / "codegraph.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("")

    captured = []
    class FakeCompleted:
        returncode = 0
        stdout = b""
        stderr = b""
    monkeypatch.setattr(proxy.subprocess, "run",
                        lambda cmd, **kw: (captured.append(cmd), FakeCompleted())[1])

    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "codegraphagent_index_project",
                                 "arguments": {}}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})

    parent_out = io.BytesIO()
    _run_proxy(parent_in, parent_out, tmp_path)

    assert len(captured) == 1
    cmd = captured[0]
    assert "index" in cmd and "--force" in cmd
    assert "init" not in cmd


def test_tools_call_index_project_reports_subprocess_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class FakeCompleted:
        returncode = 1
        stdout = b""
        stderr = b"boom: missing grammars\n"
    monkeypatch.setattr(proxy.subprocess, "run",
                        lambda cmd, **kw: FakeCompleted())

    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "codegraphagent_index_project",
                                 "arguments": {}}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})

    parent_out = io.BytesIO()
    _run_proxy(parent_in, parent_out, tmp_path)

    frames = _parse_frames(parent_out)
    index_resp = next(f for f in frames if f.get("id") == 2)
    assert index_resp["result"]["isError"] is True
    text = index_resp["result"]["content"][0]["text"]
    assert "Indexing failed" in text
    assert "boom: missing grammars" in text


def test_engine_exit_code_propagates(tmp_path: Path):
    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1})  # any frame

    parent_out = io.BytesIO()
    parent_in.seek(0)
    rc = proxy.run(
        launcher=Path(sys.executable),
        cwd=tmp_path,
        argv_override=[*FAKE_ENGINE_ARGV, "--exit-code", "42"],
        env_override={"PYTHONPATH": str(REPO_ROOT)},
        stdin=parent_in,
        stdout=parent_out,
        stderr=sys.stderr.buffer,
    )
    assert rc == 42
