# CodeGraphAgent

A [Biorouter](https://github.com/BaranziniLab/biorouter) extension (`.brxt`) that gives the agent a
pre-built code knowledge graph of a project: ask where a function is used, what it calls, or how an
area of the code fits together, and get the answer from an index instead of a grep and read loop.

It runs the upstream [CodeGraph](https://github.com/colbymchenry/codegraph) engine, version 1.6.4
(MIT, Colby McHenry), unmodified. CodeGraph indexes about 30 languages, among them Python, R,
TypeScript and JavaScript, C and C++, Rust, Go, Java, Kotlin, Swift, Ruby, PHP and Lua.

## Install

1. Download [`codegraphagent.brxt`](https://github.com/Broccolito/CodeGraphAgent/releases/latest/download/codegraphagent.brxt).
2. In Biorouter: **Settings, Extensions, Install from file**, and pick the `.brxt`; or
   `biorouter extension install codegraphagent.brxt`.

The bundle is about 30 KB and has no Python dependencies. The engine (about 60 MB) is downloaded
from upstream's own GitHub release the first time a CodeGraphAgent tool is called, checked against
the SHA-256 pinned in `src/codegraphagent/release_manifest.json`, and kept inside the extension.

## Tools

| Tool | What it does |
| --- | --- |
| `codegraph_explore` | One call returns the source of the symbols relevant to a question, the call paths between them, and what depends on them. |
| `codegraph_node` | One symbol's source and callers, or a file with line numbers. |
| `codegraph_search` | Find symbols by name (locations only). |
| `codegraph_callers` | Who calls a function. |
| `codegraphagent_index_project` | Build or refresh a project's index. |

The first four are upstream's own tools (its documented four-tool surface,
`CODEGRAPH_MCP_TOOLS=explore,node,search,callers`). Every one takes `project_dir`, the absolute
path of the project: a stdio extension is never told which folder the chat is working in. When a
call leaves it out and `BIOROUTER_WORKING_DIR` names a project folder (not the home folder, a folder
above it or the filesystem root), that folder is used.

Indexing is the user's decision, as upstream says: the agent is told to call
`codegraphagent_index_project` only when you ask for it, and the tool is marked as a write (not
read-only), so a Biorouter mode that asks before writes asks before it runs. The index lives in
`<project>/.codegraph-biorouter/`, which ignores itself in git, so it never shows in `git status`,
never collides with a project's own `.codegraph/` or with upstream's global `~/.codegraph`, and is
removed by deleting that folder. The home folder, folders above it and the filesystem root are never
indexed.

Telemetry and update checks are off: the engine always runs with `CODEGRAPH_TELEMETRY=0`,
`DO_NOT_TRACK=1` and `CODEGRAPH_NO_UPDATE_CHECK=1`.

## Settings (optional)

| Variable | Purpose |
| --- | --- |
| `CODEGRAPH_MCP_TOOLS` | Engine tools to offer, upstream names without the `codegraph_` prefix. Default `explore,node,search,callers`; `callees`, `impact`, `files` and `status` can be added. |
| `CODEGRAPH_NO_WATCH` | `1` turns off the engine's file watcher (slow filesystems such as WSL2 `/mnt` drives). The index then refreshes only when re-indexed. |
| `CODEGRAPH_ENGINE_PATH` | An already-extracted upstream 1.6.4 bundle (the folder holding `codegraph-<platform>/`), for machines without internet access. |

## How it works

```text
Biorouter ── MCP over stdio ──> codegraphagent (Python, stdlib only)
                                  │  names the project on each call (project_dir -> projectPath),
                                  │  adds codegraphagent_index_project, sets telemetry off
                                  └─> codegraph serve --mcp (upstream 1.6.4, its own Node runtime)
```

Biorouter reads an extension's tool list once, when it starts, so the shim answers with the engine's
real tool list from the start (captured from 1.6.4 into `engine_surface.json`) and downloads the
engine on the first tool call.

## Development

```bash
uv sync --extra dev
uv run pytest -q
uv run python scripts/build_brxt.py   # dist/codegraphagent.brxt, codegraphagent-<version>.brxt, SHA256SUMS
```

A release is cut by pushing a tag `v<manifest version>`; `.github/workflows/release-brxt.yml`
refuses any other tag.

## Languages

Up to 0.1.0 this repository vendored a fork of CodeGraph 0.9.7 with extra R, Julia, MATLAB and Perl
extractors. Upstream has indexed R natively since 1.0.0. Julia, MATLAB and Perl are not indexed by
1.6.4, so 0.2.0 no longer covers them.

## License

Apache-2.0 for this extension (see `LICENSE` and `NOTICE`). CodeGraph is MIT-licensed and is
downloaded from its own release; no CodeGraph code is in this repository or in the bundle.
