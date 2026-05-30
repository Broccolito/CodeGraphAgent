"""Install-mode MCP server.

When the CodeGraph engine isn't cached locally, the shim serves this
mini-MCP server first. It exposes a single tool, ``codegraphagent_check_engine``,
that downloads + verifies + extracts the engine on demand. While the engine
is missing, no other tools are visible — so the agent must call check_engine
first.

After a successful check_engine call, ``serve`` returns the launcher path so
the caller (``cli.main``) can transition into proxy mode.

Why a tool call instead of an automatic download at startup: the engine bundle
is ~45 MB and the first install takes 30-60 seconds. An automatic download
blocks the MCP ``initialize`` handshake with no progress feedback, which
shows up in BioRouter's UI as a hung extension. Pushing the work into an
explicit, agent-invoked tool call surfaces the wait time with a clear "this
will take a moment" message.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import BinaryIO

from codegraphagent import bootstrap
from codegraphagent.errors import BootstrapError


_CHECK_ENGINE_TOOL = {
    "name": "codegraphagent_check_engine",
    "description": (
        "Check whether the CodeGraph engine binary is installed locally. "
        "If not, download and install it (~45 MB, takes about 30-60 seconds "
        "on a typical connection). "
        "MUST be called before using any codegraph_* tools when the extension "
        "is first installed. Subsequent calls return immediately."
    ),
    "inputSchema": {"type": "object", "properties": {}, "required": []},
}


def serve(
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> Path | None:
    """Serve MCP in install-mode.

    Returns the engine launcher path on successful install, or None on
    shutdown / stdin EOF. The caller is expected to spawn the engine and
    enter proxy mode if a Path is returned.
    """
    inp = stdin or sys.stdin.buffer
    out = stdout or sys.stdout.buffer

    def write_frame(frame: dict) -> None:
        out.write((json.dumps(frame) + "\n").encode())
        out.flush()

    while True:
        line = inp.readline()
        if not line:
            return None

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            write_frame({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": req.get("params", {}).get(
                        "protocolVersion", "2024-11-05"
                    ),
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {
                        "name": "codegraphagent (install pending)",
                        "version": "0.1.0",
                    },
                },
            })
        elif method == "tools/list":
            write_frame({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": [_CHECK_ENGINE_TOOL]},
            })
        elif method == "tools/call":
            name = req.get("params", {}).get("name")
            if name == "codegraphagent_check_engine":
                # Re-check cache in case another process installed the engine.
                cached = bootstrap.cached_launcher()
                if cached:
                    write_frame({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{
                                "type": "text",
                                "text": (
                                    "CodeGraph engine is already installed. "
                                    "Ready to use."
                                ),
                            }],
                            "isError": False,
                        },
                    })
                    write_frame({
                        "jsonrpc": "2.0",
                        "method": "notifications/tools/list_changed",
                    })
                    return cached

                try:
                    launcher = bootstrap.ensure_engine()
                except BootstrapError as exc:
                    write_frame({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{
                                "type": "text",
                                "text": _format_bootstrap_error(exc),
                            }],
                            "isError": True,
                        },
                    })
                    continue  # stay in loop so the user can retry

                write_frame({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": (
                                "CodeGraph engine installed successfully. "
                                "You can now call any of the codegraph_* tools."
                            ),
                        }],
                        "isError": False,
                    },
                })
                write_frame({
                    "jsonrpc": "2.0",
                    "method": "notifications/tools/list_changed",
                })
                return launcher
            else:
                write_frame({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": (
                                f"Tool {name!r} is unavailable until the engine "
                                "is installed. Call codegraphagent_check_engine first."
                            ),
                        }],
                        "isError": True,
                    },
                })
        elif method == "shutdown":
            write_frame({"jsonrpc": "2.0", "id": req_id, "result": None})
            return None
        else:
            write_frame({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            })


def _format_bootstrap_error(exc: BootstrapError) -> str:
    parts = [f"CodeGraph engine install failed: {exc}"]
    if exc.url:
        parts.append(f"URL: {exc.url}")
    if exc.expected_sha and exc.observed_sha:
        parts.append(f"Expected SHA-256: {exc.expected_sha}")
        parts.append(f"Observed SHA-256: {exc.observed_sha}")
    parts.append(
        "You can retry by calling codegraphagent_check_engine again, or set "
        "the CODEGRAPH_ENGINE_PATH env var to a pre-downloaded bundle."
    )
    return "\n".join(parts)
