"""CLI entry point for codegraphagent.

Orchestrates the three pieces of the shim:
  1. paths — resolve the project root and ensure the .biorouter/codegraph
     state dir + .codegraph symlink exist.
  2. bootstrap — ensure the vendored engine bundle is downloaded, verified,
     and extracted.
  3. proxy — spawn the engine and pump MCP traffic.

If either of the first two fails, hand control to the degraded-mode error
shim so the agent gets a structured error frame rather than an opaque crash.
"""

from __future__ import annotations

from codegraphagent import bootstrap, error_shim, paths, proxy
from codegraphagent.errors import CodeGraphAgentError


def main() -> int:
    try:
        root = paths.resolve_project_root()
        paths.ensure_layout(root)
        launcher = bootstrap.ensure_engine()
    except CodeGraphAgentError as exc:
        error_shim.serve(exc)
        return 0

    return proxy.run(launcher=launcher, cwd=root)
