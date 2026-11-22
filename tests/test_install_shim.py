"""install_shim: the engine's own surface before the engine is on disk."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from codegraphagent import install_shim
from codegraphagent.errors import BootstrapError


def _send(buf: io.BytesIO, frame: dict) -> None:
    buf.write((json.dumps(frame) + "\n").encode())


def _frames(out: io.BytesIO) -> list[dict]:
    return [json.loads(l) for l in out.getvalue().decode().splitlines() if l]


def _serve(frames: list[dict], **patches):
    inp = io.BytesIO()
    for f in frames:
        _send(inp, f)
    inp.seek(0)
    out = io.BytesIO()
    return install_shim.serve(stdin=inp, stdout=out), _frames(out)


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}}}


def test_tools_list_is_the_engine_surface_from_the_start(clean_env):
    """Biorouter never re-reads a tool list, so the first one must be complete."""
    result, frames = _serve([INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                             {"jsonrpc": "2.0", "id": 3, "method": "shutdown"}])
    assert result is None
    names = [t["name"] for t in frames[1]["result"]["tools"]]
    assert names == ["codegraph_search", "codegraph_callers", "codegraph_node",
                     "codegraph_explore", "codegraphagent_index_project"]
    for tool in frames[1]["result"]["tools"][:4]:
        props = tool["inputSchema"]["properties"]
        assert "project_dir" in props and "projectPath" not in props


def test_tools_list_follows_codegraph_mcp_tools(clean_env, monkeypatch):
    monkeypatch.setenv("CODEGRAPH_MCP_TOOLS", "explore,impact")
    _, frames = _serve([INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
    names = [t["name"] for t in frames[1]["result"]["tools"]]
    assert names == ["codegraph_impact", "codegraph_explore", "codegraphagent_index_project"]


def test_initialize_carries_the_engine_instructions_and_the_note(clean_env):
    _, frames = _serve([INIT])
    result = frames[0]["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "codegraphagent"
    assert "Codegraph" in result["instructions"]
    assert "codegraphagent_index_project" in result["instructions"]
    assert "projectPath" not in result["instructions"].split("## In Biorouter")[0]


def test_first_call_installs_then_hands_over_the_pending_call(tmp_path: Path, clean_env):
    launcher = tmp_path / "launcher"
    launcher.write_text("")
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "codegraph_explore", "arguments": {"query": "x"}}}
    with patch.object(install_shim.bootstrap, "cached_launcher", return_value=None), \
         patch.object(install_shim.bootstrap, "ensure_engine", return_value=launcher) as ensure:
        result, frames = _serve([INIT, call])
    ensure.assert_called_once()
    assert result == (launcher, INIT, call)
    # The pending call is answered by the engine, not by the shim.
    assert [f.get("id") for f in frames] == [1]


def test_a_failed_download_is_a_tool_error_and_the_shim_stays(clean_env):
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "codegraph_explore", "arguments": {}}}
    err = BootstrapError("net down", url="https://example.com/x.tar.gz")
    with patch.object(install_shim.bootstrap, "cached_launcher", return_value=None), \
         patch.object(install_shim.bootstrap, "ensure_engine", side_effect=err):
        result, frames = _serve([INIT, call, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"}])
    assert result is None
    assert frames[1]["result"]["isError"] is True
    text = frames[1]["result"]["content"][0]["text"]
    assert "net down" in text and "https://example.com/x.tar.gz" in text and "retries" in text


def test_notifications_get_no_reply(clean_env):
    """0.1.0 answered notifications/initialized with an id-less error frame,
    which the MCP client logged as a malformed message on every start."""
    result, frames = _serve([
        INIT,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ])
    assert result is None
    assert [f.get("id") for f in frames] == [1, 2, 3]
    assert frames[1]["result"] == {}


def test_surface_matches_the_pinned_engine():
    import json as _json
    from codegraphagent import bootstrap
    surface = _json.loads((Path(install_shim.__file__).parent / "engine_surface.json").read_text())
    manifest = _json.loads((Path(bootstrap.__file__).parent / "release_manifest.json").read_text())
    assert surface["engine_version"] == manifest["engine_version"]
    assert len(surface["tools"]) == 8
