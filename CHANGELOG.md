# Changelog

## v0.2.0 (2026-11-22)

- The engine is now upstream CodeGraph 1.6.4's own release archive (pinned per platform by
  SHA-256), not a vendored 0.9.7 fork; the `engine/` tree and the `engine-v*` builds are gone.
  Julia, MATLAB and Perl are no longer indexed; R is indexed by upstream.
- Starts anywhere: the project is named on each call with `project_dir` (falling back to
  `BIOROUTER_WORKING_DIR` only when that is a project folder, never the home folder). 0.1.0 took
  the home folder as the project when Biorouter ran there and refused to start beside upstream's
  global `~/.codegraph`.
- The index lives in `<project>/.codegraph-biorouter/` (ignored by git, no symlink, no edit to
  the project's `.gitignore`). A 0.1.0 index (`.biorouter/codegraph/` plus a `.codegraph`
  symlink) is no longer read and can be deleted; re-index the project once.
- Upstream's four-tool surface (explore, node, search, callers) plus
  `codegraphagent_index_project`, which is to be called only when the user asks and is marked as
  a write. The full tool list is served from the start, because Biorouter does not re-read a tool
  list; the engine downloads on the first tool call. `codegraphagent_check_engine` is gone.
- Telemetry and update checks are always off (`CODEGRAPH_TELEMETRY=0`, `DO_NOT_TRACK=1`,
  `CODEGRAPH_NO_UPDATE_CHECK=1`).
- Fixed: the shim answered `notifications/initialized` with an id-less error frame, which the MCP
  client logged as invalid on every start.
- `CODEGRAPH_ENGINE_VERSION` is removed (an unpinned engine cannot be verified).
- Releases are cut from a pushed `v*` tag that must equal the manifest version, with
  `codegraphagent.brxt`, `codegraphagent-<version>.brxt` and `SHA256SUMS`.

## v0.1.0 (in progress)

- Added 4 new language extractors via Plan 2: R, Julia, MATLAB, Perl.
- Engine bumped to `engine-v0.2.0` (vendored from upstream v0.9.7 with bio-language patches).
- `.m` extension now content-disambiguated between MATLAB and Objective-C.
- 31 new engine tests covering the new languages (1123 total passing).

## v0.1.0-rc1 (2026-05-30)

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
- Added `codegraphagent_index_project` MCP tool so agents can build the
  CodeGraph index from within a BioRouter session (upstream's engine
  expects `codegraph init` to be run from a terminal first). Proxy is now
  JSON-RPC-frame-aware to intercept this tool while passing everything
  else through.
