"""error_shim — minimal MCP server that surfaces a single error tool when the
shim couldn't reach the engine."""

from __future__ import annotations

import io
import json
import threading

from codegraphagent import error_shim
from codegraphagent.errors import BootstrapError, LayoutConflictError


def _send(stream: io.BytesIO, frame: dict) -> None:
    stream.write((json.dumps(frame) + "\n").encode())


def test_error_shim_lists_bootstrap_error_tool():
    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})
    parent_in.seek(0)
    parent_out = io.BytesIO()

    exc = BootstrapError(
        "boom",
        url="https://example.com/x.tar.gz",
        expected_sha="abc",
        observed_sha="def",
    )
    error_shim.serve(exc, stdin=parent_in, stdout=parent_out)

    frames = [json.loads(l) for l in parent_out.getvalue().decode().splitlines() if l]
    # frames: initialize response, tools/list response, shutdown response
    assert len(frames) == 3
    tools_list = frames[1]["result"]["tools"]
    assert any(t["name"] == "codegraphagent_bootstrap_error" for t in tools_list)


def test_error_shim_call_returns_error_details():
    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(parent_in, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "codegraphagent_bootstrap_error", "arguments": {}},
    })
    _send(parent_in, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})
    parent_in.seek(0)
    parent_out = io.BytesIO()

    exc = BootstrapError(
        "download failed",
        url="https://example.com/x.tar.gz",
    )
    error_shim.serve(exc, stdin=parent_in, stdout=parent_out)

    frames = [json.loads(l) for l in parent_out.getvalue().decode().splitlines() if l]
    call_result = frames[1]["result"]
    text = call_result["content"][0]["text"]
    assert "download failed" in text
    assert "https://example.com/x.tar.gz" in text


def test_error_shim_layout_conflict():
    parent_in = io.BytesIO()
    _send(parent_in, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    _send(parent_in, {"jsonrpc": "2.0", "id": 3, "method": "shutdown"})
    parent_in.seek(0)
    parent_out = io.BytesIO()

    exc = LayoutConflictError("path exists", path="/tmp/foo/.codegraph")
    error_shim.serve(exc, stdin=parent_in, stdout=parent_out)

    frames = [json.loads(l) for l in parent_out.getvalue().decode().splitlines() if l]
    tools_list = frames[1]["result"]["tools"]
    assert any(t["name"] == "codegraphagent_setup_error" for t in tools_list)
