"""CLI entry point for codegraphagent.

1. bootstrap.cached_launcher: is the pinned engine already installed?
2. install_shim (only if not): serves the engine's own tool surface (captured
   from upstream 1.6.4) and, on the first tool call, downloads, verifies and
   extracts the engine, then hands back the launcher, the client's initialize
   request and that pending call.
3. proxy: start the engine (``codegraph serve --mcp``) in an empty run
   folder and pump MCP traffic, naming the project on each call.

Nothing here looks at the current folder: the project comes from each tool
call's ``project_dir`` (see paths and proxy), so starting the extension in the
home folder, next to upstream CodeGraph's global ``~/.codegraph``, works.
"""

from __future__ import annotations

from codegraphagent import __version__, bootstrap, error_shim, install_shim, proxy
from codegraphagent.errors import CodeGraphAgentError


def main() -> int:
    try:
        cached = bootstrap.cached_launcher()
    except CodeGraphAgentError as exc:
        error_shim.serve(exc)
        return 0
    if cached is not None:
        return proxy.run(launcher=cached)

    installed = install_shim.serve()
    if installed is None:
        return 0
    launcher, initialize_request, pending_call = installed
    if initialize_request is None:
        initialize_request = {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "codegraphagent", "version": __version__}},
        }
    return proxy.run(launcher=launcher, replay_initialize=initialize_request, pending_call=pending_call)
