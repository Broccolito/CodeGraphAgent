"""Degraded-mode MCP server.

When bootstrap or layout setup fails, the main shim hands control here. This
server still satisfies the MCP `initialize` + `tools/list` + `tools/call`
handshake — but the only tool it offers returns the underlying error so the
agent (and the user reading the log) can see exactly what went wrong.

Implemented in pure stdlib to keep it functional even if fastmcp's import
itself is what failed.
"""

from __future__ import annotations

import json
import sys
from typing import BinaryIO

from codegraphagent.errors import (
    BootstrapError,
    CodeGraphAgentError,
    LayoutConflictError,
)


def _tool_for(exc: CodeGraphAgentError) -> dict:
    """Return the synthetic tool descriptor matching the given error type."""
    if isinstance(exc, BootstrapError):
        return {
            "name": "codegraphagent_bootstrap_error",
            "description": (
                "CodeGraphAgent failed to download or verify the engine bundle. "
                "Call this tool to see the underlying error."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }
    if isinstance(exc, LayoutConflictError):
        return {
            "name": "codegraphagent_setup_error",
            "description": (
                "CodeGraphAgent could not set up the .biorouter/codegraph "
                "symlink. Call this tool to see the remediation steps."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }
    return {
        "name": "codegraphagent_error",
        "description": "CodeGraphAgent encountered an internal error.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    }


def _error_text(exc: CodeGraphAgentError) -> str:
    parts = [f"CodeGraphAgent error: {exc}"]
    if isinstance(exc, BootstrapError):
        if exc.url:
            parts.append(f"URL: {exc.url}")
        if exc.expected_sha and exc.observed_sha:
            parts.append(f"Expected SHA-256: {exc.expected_sha}")
            parts.append(f"Observed SHA-256: {exc.observed_sha}")
        parts.append(
            "Recovery: retry; or set CODEGRAPH_ENGINE_PATH to a pre-downloaded "
            "bundle; or pin CODEGRAPH_ENGINE_VERSION to a different release."
        )
    elif isinstance(exc, LayoutConflictError):
        parts.append(f"Path: {exc.path}")
        parts.append(
            "Recovery: rename or remove the conflicting .codegraph directory, "
            "then restart the CodeGraphAgent extension."
        )
    return "\n".join(parts)


def serve(
    exc: CodeGraphAgentError,
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> None:
    """Serve MCP requests in degraded mode until `shutdown` is received."""
    inp = stdin or sys.stdin.buffer
    out = stdout or sys.stdout.buffer
    tool = _tool_for(exc)

    while True:
        line = inp.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": req.get("params", {}).get(
                        "protocolVersion", "2024-11-05"
                    ),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "codegraphagent (degraded)", "version": "0.1.0"},
                },
            }
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": [tool]},
            }
        elif method == "tools/call":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": _error_text(exc)}],
                    "isError": True,
                },
            }
        elif method == "shutdown":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": None}
            out.write((json.dumps(resp) + "\n").encode())
            out.flush()
            break
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        out.write((json.dumps(resp) + "\n").encode())
        out.flush()
