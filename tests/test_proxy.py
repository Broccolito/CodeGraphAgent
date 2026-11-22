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


class _FakeCompleted:
    def __init__(self, rc=0, stdout=b"", stderr=b""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def _index_call(arguments: dict) -> list[dict]:
    return [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "codegraphagent_index_project", "arguments": arguments}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ]


def _run_frames(frames: list[dict], tmp_path: Path) -> list[dict]:
    parent_in = io.BytesIO()
    for frame in frames:
        _send(parent_in, frame)
    parent_out = io.BytesIO()
    assert _run_proxy(parent_in, parent_out, tmp_path) == 0
    return _parse_frames(parent_out)


@pytest.fixture
def project(tmp_path: Path, clean_env) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    return proj


def test_index_project_runs_init_in_the_named_project(project: Path, tmp_path: Path, monkeypatch):
    calls = []
    monkeypatch.setattr(proxy.subprocess, "run",
                        lambda cmd, **kw: (calls.append((cmd, kw)), _FakeCompleted(0, b"Indexed 3 files.\n"))[1])
    frames = _run_frames(_index_call({"project_dir": str(project)}), tmp_path)

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[0] == sys.executable
    assert cmd[1:] == ["init", str(project.resolve()), "--yes", "--local-only"]
    assert "--force" not in cmd
    assert kwargs["cwd"] == str(project.resolve())
    env = kwargs["env"]
    assert env["CODEGRAPH_TELEMETRY"] == "0" and env["DO_NOT_TRACK"] == "1"
    assert env["CODEGRAPH_DIR"] == ".codegraph-biorouter"
    resp = next(f for f in frames if f.get("id") == 2)
    assert resp["result"]["isError"] is False
    assert "Indexed 3 files" in resp["result"]["content"][0]["text"]


def test_index_project_reindexes_when_the_index_exists(project: Path, tmp_path: Path, monkeypatch):
    (project / ".codegraph-biorouter").mkdir()
    (project / ".codegraph-biorouter" / "codegraph.db").write_text("")
    calls = []
    monkeypatch.setattr(proxy.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), _FakeCompleted())[1])
    _run_frames(_index_call({"project_dir": str(project)}), tmp_path)
    assert calls[0][1:] == ["index", str(project.resolve()), "--quiet"]


def test_index_project_refuses_home(tmp_path: Path, clean_env, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(proxy.paths.Path, "home", classmethod(lambda cls: home))
    calls = []
    monkeypatch.setattr(proxy.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), _FakeCompleted())[1])
    frames = _run_frames(_index_call({"project_dir": str(home)}), tmp_path)
    assert calls == []
    resp = next(f for f in frames if f.get("id") == 2)
    assert resp["result"]["isError"] is True
    assert "home folder" in resp["result"]["content"][0]["text"]


def test_index_project_without_a_project_asks_for_one(tmp_path: Path, clean_env, monkeypatch):
    calls = []
    monkeypatch.setattr(proxy.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), _FakeCompleted())[1])
    frames = _run_frames(_index_call({}), tmp_path)
    assert calls == []
    resp = next(f for f in frames if f.get("id") == 2)
    assert resp["result"]["isError"] is True
    assert "project_dir" in resp["result"]["content"][0]["text"]


def test_index_project_uses_the_fallback_project(project: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(project))
    calls = []
    monkeypatch.setattr(proxy.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), _FakeCompleted())[1])
    _run_frames(_index_call({}), tmp_path)
    assert calls[0][2] == str(project.resolve())


def test_index_project_reports_subprocess_failure(project: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(proxy.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(1, b"", b"boom: missing grammars\n"))
    frames = _run_frames(_index_call({"project_dir": str(project)}), tmp_path)
    resp = next(f for f in frames if f.get("id") == 2)
    assert resp["result"]["isError"] is True
    text = resp["result"]["content"][0]["text"]
    assert "failed" in text and "boom: missing grammars" in text


def test_tools_list_renames_project_path_and_marks_it_required_without_fallback(
    tmp_path: Path, clean_env
):
    frames = _run_frames([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ], tmp_path)
    tools = {t["name"]: t for t in next(f for f in frames if f.get("id") == 2)["result"]["tools"]}
    for name in ("codegraph_search", "codegraph_callers"):
        schema = tools[name]["inputSchema"]
        assert "projectPath" not in schema["properties"]
        assert "project_dir" in schema["properties"]
        assert "project_dir" in schema["required"]
        assert "projectPath" not in schema["required"]
    assert "projectPath" not in tools["codegraph_search"]["description"]
    index_tool = tools["codegraph_index_project".replace("codegraph_", "codegraphagent_")]
    assert index_tool["annotations"]["readOnlyHint"] is False
    assert index_tool["inputSchema"]["required"] == ["project_dir"]


def test_tools_list_makes_project_dir_optional_with_a_fallback(project: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(project))
    frames = _run_frames([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ], tmp_path)
    tools = {t["name"]: t for t in next(f for f in frames if f.get("id") == 2)["result"]["tools"]}
    assert tools["codegraph_search"]["inputSchema"]["required"] == ["query"]


def test_initialize_instructions_get_the_biorouter_note(tmp_path: Path, clean_env):
    frames = _run_frames([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ], tmp_path)
    instructions = next(f for f in frames if f.get("id") == 1)["result"]["instructions"]
    assert instructions.startswith("Fake instructions. Pass project_dir.")
    assert "codegraphagent_index_project" in instructions
    assert ".codegraph-biorouter" in instructions


def test_tools_call_maps_project_dir_to_project_path(project: Path, tmp_path: Path):
    frames = _run_frames([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "codegraph_search", "arguments": {"query": "q", "project_dir": str(project)}}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ], tmp_path)
    text = next(f for f in frames if f.get("id") == 2)["result"]["content"][0]["text"]
    assert f"projectPath={str(project.resolve())!r}" in text
    assert "has_project_dir=False" in text


def test_tools_call_without_a_project_uses_the_fallback(project: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(project))
    frames = _run_frames([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "codegraph_search", "arguments": {"query": "q"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ], tmp_path)
    text = next(f for f in frames if f.get("id") == 2)["result"]["content"][0]["text"]
    assert f"projectPath={str(project.resolve())!r}" in text


def test_tools_call_never_falls_back_to_home(tmp_path: Path, clean_env, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(proxy.paths.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(home))
    frames = _run_frames([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "codegraph_search", "arguments": {"query": "q"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ], tmp_path)
    text = next(f for f in frames if f.get("id") == 2)["result"]["content"][0]["text"]
    assert "projectPath=None" in text


def test_replayed_initialize_reaches_a_strict_engine_first(tmp_path: Path, clean_env):
    """After a first-use install the client's handshake was answered by the
    install shim; the engine must still be initialized before tools/list."""
    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    _send(parent_in, {"jsonrpc": "2.0", "id": 8, "method": "shutdown"})
    parent_in.seek(0)
    parent_out = io.BytesIO()
    rc = proxy.run(
        launcher=Path(sys.executable),
        cwd=tmp_path,
        argv_override=[*FAKE_ENGINE_ARGV, "--strict-init"],
        env_override={"PYTHONPATH": str(REPO_ROOT)},
        stdin=parent_in,
        stdout=parent_out,
        stderr=sys.stderr.buffer,
        replay_initialize={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert rc == 0
    frames = _parse_frames(parent_out)
    # The replayed initialize's answer is swallowed; the client sees only its own ids.
    assert [f.get("id") for f in frames] == [7, 8]
    assert "result" in frames[0] and frames[0]["result"]["tools"]


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


def test_pending_call_is_answered_by_the_engine_after_the_replay(project: Path, tmp_path: Path):
    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 8, "method": "shutdown"})
    parent_in.seek(0)
    parent_out = io.BytesIO()
    rc = proxy.run(
        launcher=Path(sys.executable),
        cwd=tmp_path,
        argv_override=[*FAKE_ENGINE_ARGV, "--strict-init"],
        env_override={"PYTHONPATH": str(REPO_ROOT)},
        stdin=parent_in,
        stdout=parent_out,
        stderr=sys.stderr.buffer,
        replay_initialize={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        pending_call={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "codegraph_search",
                                 "arguments": {"query": "q", "project_dir": str(project)}}},
    )
    assert rc == 0
    frames = _parse_frames(parent_out)
    assert [f.get("id") for f in frames] == [2, 8]
    assert f"projectPath={str(project.resolve())!r}" in frames[0]["result"]["content"][0]["text"]
