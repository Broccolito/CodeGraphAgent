# Changelog

## v0.1.0-rc1 (in progress)

- Initial release scaffolding.
- Python proxy shim (paths, bootstrap, proxy, error shim).
- Vendored CodeGraph engine from upstream v0.9.7.
- Verified `build-bundle.sh` produces a working local-platform bundle.
- Fixed `_launcher_path` in `bootstrap.py`: tarball extracts to
  `engine/codegraph-<tag>/bin/codegraph` (not `engine/bin/codegraph`);
  updated path to include the platform subdirectory.
- End-to-end smoke test verified: shim spawns engine, tools list returns ~9
  codegraph_* tools, symlink + DB materialize at expected paths.
