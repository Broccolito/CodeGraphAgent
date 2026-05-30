# CodeGraphAgent

A [BioRouter](https://github.com/BaranziniLab/BioRouter) extension (`.brxt`)
that provides a pre-indexed code knowledge graph (callers, callees, impact,
trace) via a vendored fork of [CodeGraph](https://github.com/colbymchenry/codegraph).

## What it does

**New in v0.1.0:** Adds R, Julia, MATLAB, and Perl language support on top of upstream's 19 languages.

CodeGraphAgent installs into a BioRouter session and exposes 10 MCP tools
(`codegraph_search`, `codegraph_callers`, `codegraph_callees`,
`codegraph_trace`, `codegraph_impact`, `codegraph_node`, `codegraph_explore`,
`codegraph_context`, `codegraph_status`, `codegraph_files`) that let the
agent answer "where is X used?", "what does Y call?", and "what breaks if I
change Z?" against the current project — without re-parsing the codebase on
every query.

The index lives at `<project>/.biorouter/codegraph/codegraph.db`.

Two helper tools are added by the shim:
- `codegraphagent_check_engine` — installs the engine bundle on first use (one-time).
- `codegraphagent_index_project` — builds (or rebuilds) the index for the current project. Must be called once before the query tools (codegraph_search, codegraph_callers, etc.) return results.

## First-time install flow

When you first enable CodeGraphAgent in a session, the engine binary (~45 MB)
is **not** downloaded automatically. Instead, the extension exposes a single
tool, `codegraphagent_check_engine`. Ask the agent to call it, or call it
yourself — it'll download + verify + extract the engine, taking about
30-60 seconds. After that, all the `codegraph_*` tools become available and
work transparently.

This is intentional: the download is deliberate and visible, rather than
hidden in a silent stall during MCP initialize.

After the engine is installed, the agent also needs to **index your project** before queries return results. Call `codegraphagent_index_project` (or ask the agent to do it). Indexing takes ~1s for tiny projects, longer for monorepos. The engine refuses search/caller/etc queries until an index exists.

## Install

Once a `.brxt` release is published, BioRouter installs the extension via:
`Settings → Extensions → Install from file → codegraphagent.brxt`.

## Configuration (optional env vars)

| Variable | Purpose |
| --- | --- |
| `CODEGRAPH_ENGINE_PATH` | Path to an already-extracted engine bundle. Skips the on-first-use download — useful for air-gapped or CI environments. |
| `CODEGRAPH_ENGINE_VERSION` | Override the pinned engine release tag. |
| `CODEGRAPH_NO_WATCH` | Set to `1` to disable the file watcher (slow filesystems like WSL2). |

## Status

v0.1.0-rc1 — initial release wrapping upstream CodeGraph unchanged.
See [CHANGELOG](CHANGELOG.md).

## Credits

Engine vendored from [CodeGraph](https://github.com/colbymchenry/codegraph)
(MIT, © Colby McHenry). The full upstream license is at `engine/LICENSE`.
