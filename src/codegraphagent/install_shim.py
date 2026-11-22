"""Install-mode MCP server, used until the engine is on disk.

Biorouter reads an extension's tool list once, when the extension starts, and
does not re-read it on ``notifications/tools/list_changed``. So the shim offers
the engine's real tool surface from the first ``tools/list``: the tool
definitions and server instructions upstream CodeGraph 1.6.4 itself serves,
captured into ``engine_surface.json`` and passed through the same rewrite the
proxy applies (``project_dir``, the index tool, the Biorouter note).

The first ``tools/call`` downloads, verifies and extracts the pinned engine
(about 60 MB, once per install; seconds on a fast connection). The shim then
returns the launcher, the client's ``initialize`` request and that pending
call, and the caller starts the engine, replays the handshake and forwards the
call. A failed download is answered as a tool error and the shim stays in
install mode, so the next call retries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import BinaryIO

from codegraphagent import __version__, bootstrap, paths, proxy
from codegraphagent.errors import BootstrapError

_SURFACE_PATH = Path(__file__).parent / "engine_surface.json"


def _surface() -> dict:
    with _SURFACE_PATH.open() as fh:
        return json.load(fh)


def static_tools() -> list[dict]:
    """The engine tools ``CODEGRAPH_MCP_TOOLS`` allows, as upstream defines them."""
    allow_raw = paths.engine_env().get("CODEGRAPH_MCP_TOOLS", "")
    allow = {s.strip().removeprefix("codegraph_") for s in allow_raw.split(",") if s.strip()}
    tools = _surface()["tools"]
    return [t for t in tools if t["name"].removeprefix("codegraph_") in allow] if allow else tools


def static_initialize_result(requested_version: str | None) -> dict:
    surface = _surface()
    result = {
        "protocolVersion": requested_version or surface.get("protocolVersion", "2024-11-05"),
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "codegraphagent", "version": __version__},
        "instructions": surface.get("instructions", ""),
    }
    return proxy.rewrite_initialize(result)


def serve(
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> tuple[Path, dict | None, dict] | None:
    """Serve MCP in install mode.

    Returns ``(launcher, initialize_request, pending_call)`` once the engine is
    installed, or None on shutdown / end of input.
    """
    inp = stdin or sys.stdin.buffer
    out = stdout or sys.stdout.buffer

    def write_frame(frame: dict) -> None:
        out.write((json.dumps(frame) + "\n").encode())
        out.flush()

    initialize_request: dict | None = None

    while True:
        line = inp.readline()
        if not line:
            return None
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(req, dict):
            continue
        method = req.get("method")
        req_id = req.get("id")

        if "id" not in req or method is None:
            # A notification (never answered), or a response to nothing we sent.
            continue

        if method == "initialize":
            initialize_request = req
            params = req.get("params") if isinstance(req.get("params"), dict) else {}
            write_frame({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": static_initialize_result(params.get("protocolVersion")),
            })
        elif method == "tools/list":
            write_frame({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": proxy.rewrite_tools_list({"tools": static_tools()}),
            })
        elif method == "tools/call":
            try:
                launcher = bootstrap.cached_launcher() or bootstrap.ensure_engine()
            except BootstrapError as exc:
                write_frame({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": _format_bootstrap_error(exc)}],
                        "isError": True,
                    },
                })
                continue  # stay in install mode; the next call retries
            return launcher, initialize_request, req
        elif method == "ping":
            write_frame({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "shutdown":
            write_frame({"jsonrpc": "2.0", "id": req_id, "result": None})
            return None
        elif method in ("resources/list", "prompts/list"):
            key = "resources" if method == "resources/list" else "prompts"
            write_frame({"jsonrpc": "2.0", "id": req_id, "result": {key: []}})
        else:
            write_frame({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


def _format_bootstrap_error(exc: BootstrapError) -> str:
    parts = [f"CodeGraph engine install failed: {exc}"]
    if exc.url:
        parts.append(f"URL: {exc.url}")
    if exc.expected_sha and exc.observed_sha:
        parts.append(f"Expected SHA-256: {exc.expected_sha}")
        parts.append(f"Observed SHA-256: {exc.observed_sha}")
    parts.append(
        "Calling the tool again retries the download. On a machine without "
        "internet access, set CODEGRAPH_ENGINE_PATH to an extracted upstream "
        f"CodeGraph {_surface()['engine_version']} bundle."
    )
    return "\n".join(parts)
