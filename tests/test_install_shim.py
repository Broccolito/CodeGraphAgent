"""install_shim — MCP server that exposes only the check_engine tool until
the CodeGraph engine bundle is downloaded."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codegraphagent import install_shim
from codegraphagent.errors import BootstrapError


def _send(stream: io.BytesIO, frame: dict) -> None:
    stream.write((json.dumps(frame) + "\n").encode())


def test_initialize_advertises_list_changed_capability():
    inp = io.BytesIO()
    _send(inp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(inp, {"jsonrpc": "2.0", "id": 2, "method": "shutdown"})
    inp.seek(0)
    out = io.BytesIO()

    install_shim.serve(stdin=inp, stdout=out)

    frames = [json.loads(l) for l in out.getvalue().decode().splitlines() if l]
    assert frames[0]["result"]["capabilities"]["tools"]["listChanged"] is True


def test_tools_list_only_exposes_check_engine():
    inp = io.BytesIO()
    _send(inp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(inp, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    _send(inp, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})
    inp.seek(0)
    out = io.BytesIO()

    install_shim.serve(stdin=inp, stdout=out)

    frames = [json.loads(l) for l in out.getvalue().decode().splitlines() if l]
    tools = frames[1]["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "codegraphagent_check_engine"


def test_check_engine_when_already_cached_returns_launcher(tmp_path: Path):
    launcher = tmp_path / "launcher"
    launcher.write_text("")

    inp = io.BytesIO()
    _send(inp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(inp, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "codegraphagent_check_engine", "arguments": {}},
    })
    inp.seek(0)
    out = io.BytesIO()

    with patch.object(install_shim.bootstrap, "cached_launcher", return_value=launcher):
        result = install_shim.serve(stdin=inp, stdout=out)

    assert result == launcher
    frames = [json.loads(l) for l in out.getvalue().decode().splitlines() if l]
    # initialize response, tool-call response, list_changed notification
    assert len(frames) == 3
    assert "already installed" in frames[1]["result"]["content"][0]["text"]
    assert frames[2]["method"] == "notifications/tools/list_changed"


def test_check_engine_triggers_install_when_not_cached(tmp_path: Path):
    launcher = tmp_path / "launcher"
    launcher.write_text("")

    inp = io.BytesIO()
    _send(inp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(inp, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "codegraphagent_check_engine", "arguments": {}},
    })
    inp.seek(0)
    out = io.BytesIO()

    with patch.object(install_shim.bootstrap, "cached_launcher", return_value=None), \
         patch.object(install_shim.bootstrap, "ensure_engine", return_value=launcher) as mock_install:
        result = install_shim.serve(stdin=inp, stdout=out)

    mock_install.assert_called_once()
    assert result == launcher
    frames = [json.loads(l) for l in out.getvalue().decode().splitlines() if l]
    assert "installed successfully" in frames[1]["result"]["content"][0]["text"]
    assert frames[2]["method"] == "notifications/tools/list_changed"


def test_check_engine_returns_error_on_bootstrap_failure_then_stays_in_loop(tmp_path: Path):
    inp = io.BytesIO()
    _send(inp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(inp, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "codegraphagent_check_engine", "arguments": {}},
    })
    _send(inp, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})
    inp.seek(0)
    out = io.BytesIO()

    err = BootstrapError("net down", url="https://example.com/x.tar.gz")
    with patch.object(install_shim.bootstrap, "cached_launcher", return_value=None), \
         patch.object(install_shim.bootstrap, "ensure_engine", side_effect=err):
        result = install_shim.serve(stdin=inp, stdout=out)

    assert result is None  # stayed in loop until shutdown, never transitioned to proxy
    frames = [json.loads(l) for l in out.getvalue().decode().splitlines() if l]
    tool_resp = frames[1]
    assert tool_resp["result"]["isError"] is True
    assert "net down" in tool_resp["result"]["content"][0]["text"]
    assert "https://example.com/x.tar.gz" in tool_resp["result"]["content"][0]["text"]


def test_unknown_tool_returns_error_telling_agent_to_call_check_engine_first():
    inp = io.BytesIO()
    _send(inp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(inp, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "codegraph_search", "arguments": {}},
    })
    _send(inp, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})
    inp.seek(0)
    out = io.BytesIO()

    install_shim.serve(stdin=inp, stdout=out)

    frames = [json.loads(l) for l in out.getvalue().decode().splitlines() if l]
    assert frames[1]["result"]["isError"] is True
    assert "check_engine" in frames[1]["result"]["content"][0]["text"]


def test_shutdown_returns_none():
    inp = io.BytesIO()
    _send(inp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(inp, {"jsonrpc": "2.0", "id": 2, "method": "shutdown"})
    inp.seek(0)
    out = io.BytesIO()

    result = install_shim.serve(stdin=inp, stdout=out)
    assert result is None
