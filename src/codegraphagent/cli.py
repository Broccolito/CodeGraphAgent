"""CLI entry point for codegraphagent.

Orchestrates the three (or four) pieces of the shim:
  1. paths — resolve the project root and ensure the .biorouter/codegraph
     state dir + .codegraph symlink exist.
  2. bootstrap.cached_launcher — read-only check: is the engine bundle
     already installed?
  3. install_shim (only if not cached) — serves a minimal MCP server with
     a single tool (codegraphagent_check_engine) that downloads + extracts
     the engine on demand. Returns the launcher path when install succeeds.
  4. proxy — spawn the engine and pump MCP traffic.

If the layout step fails (LayoutConflictError), we serve the legacy error_shim
to surface that failure to the agent as a tool error. BootstrapError no longer
happens in this function — it's caught inside install_shim and returned as a
tool result so the user can see it and retry.
"""

from __future__ import annotations

from codegraphagent import bootstrap, error_shim, install_shim, paths, proxy
from codegraphagent.errors import CodeGraphAgentError


def main() -> int:
    try:
        root = paths.resolve_project_root()
        paths.ensure_layout(root)
    except CodeGraphAgentError as exc:
        error_shim.serve(exc)
        return 0

    cached = bootstrap.cached_launcher()
    if cached is not None:
        return proxy.run(launcher=cached, cwd=root)

    # Engine not cached — serve install-mode until the agent calls
    # codegraphagent_check_engine (which triggers the download), or until
    # shutdown / EOF.
    launcher = install_shim.serve()
    if launcher is None:
        return 0
    return proxy.run(launcher=launcher, cwd=root)
