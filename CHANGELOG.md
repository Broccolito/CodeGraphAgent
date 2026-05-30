# Changelog

## v0.1.0-rc1 (in progress)

- Initial release scaffolding.
- Python proxy shim (paths, bootstrap, proxy, error shim).
- Vendored CodeGraph engine from upstream v0.9.7.
- Verified `build-bundle.sh` produces a working local-platform bundle.
- End-to-end smoke test verified: shim spawns engine, tools list returns ~10
  codegraph_* tools, symlink + DB materialize at expected paths.
- **UX revision:** the engine binary (~45 MB) is no longer downloaded
  silently on first start. Instead, the shim exposes a single
  `codegraphagent_check_engine` tool that the agent must call first to
  trigger the download. Subsequent calls return immediately. This replaces
  a silent 30-60s stall during MCP initialize with a visible, deliberate
  tool call.
