# CodeGraphAgent

A [BioRouter](https://github.com/BaranziniLab/BioRouter) extension (`.brxt`)
that gives the agent a **pre-indexed code knowledge graph**. Ask
*"where is X used?"*, *"what does Y call?"*, or *"what breaks if I change Z?"*
and get answers in milliseconds — without grepping the codebase on every
query.

Built on a vendored fork of [CodeGraph](https://github.com/colbymchenry/codegraph)
(MIT, © Colby McHenry) with **bioinformatics-friendly language additions**:
R, Julia, MATLAB, and Perl on top of upstream's 19.

[![Latest release](https://img.shields.io/github/v/release/Broccolito/CodeGraphAgent?include_prereleases)](https://github.com/Broccolito/CodeGraphAgent/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Install

1. Download [`codegraphagent.brxt`](https://github.com/Broccolito/CodeGraphAgent/releases/latest/download/codegraphagent.brxt) (~18 KB)
2. In BioRouter: **Settings → Extensions → Install from file** → select the `.brxt`
3. Enable the extension in your session

That's it. `uv sync` finishes in seconds — there are zero external Python dependencies.

## First-run flow

The first time you use the extension in a session, the agent sees a single tool:

- **`codegraphagent_check_engine`** — call this first. Downloads, verifies, and extracts the CodeGraph engine bundle (~45 MB, 30–60 s on a typical connection). One-time per machine.

After the engine is installed, the agent gets the full toolkit:

- **`codegraphagent_index_project`** — build (or rebuild) the index for the current project. Must be called once before queries return results; re-call after major code changes.
- The engine's 10 query tools (next section).

The two-step flow is deliberate: an explicit, agent-visible install is better UX than a silent 30–60 second stall during MCP initialize.

## Query tools (proxied from the engine)

| Tool | Question it answers |
| --- | --- |
| `codegraph_search` | Find symbols by name (FTS5). |
| `codegraph_callers` | Who calls function X? |
| `codegraph_callees` | What does function X call? |
| `codegraph_trace` | Show call paths between two symbols. |
| `codegraph_impact` | What's affected if I change X? |
| `codegraph_node` | Details + source for a specific symbol. |
| `codegraph_explore` | Group related symbols by file. |
| `codegraph_context` | Build a relevant context window for a task. |
| `codegraph_status` | Index health and statistics. |
| `codegraph_files` | Project file tree with per-file symbol counts. |

The index lives at `<project>/.biorouter/codegraph/codegraph.db` (per-project, SQLite, WAL mode).

## Languages supported

**v0.1.0 adds 4 new languages on top of upstream's 19** (23 total):

| Category | Languages |
| --- | --- |
| **Bioinformatics & numerics** (added by us) | R, Julia, MATLAB, Perl |
| Scripting | Python, Ruby, Lua, Luau |
| Compiled systems | Rust, Go, C, C++, C#, Swift, Kotlin |
| Web | TypeScript, JavaScript, PHP, Dart |
| Other | Java, Scala, Objective-C, Pascal |

For the `.m` extension (shared between MATLAB and Objective-C), the engine sniffs file content for ObjC markers (`@interface`, `@implementation`, `#import`, `#include`) and falls back to MATLAB when none are present.

## Configuration (optional env vars)

| Variable | Purpose |
| --- | --- |
| `CODEGRAPH_ENGINE_PATH` | Path to an already-extracted engine bundle. Skips the on-first-use download — useful for air-gapped or CI environments. |
| `CODEGRAPH_ENGINE_VERSION` | Override the pinned engine release tag. |
| `CODEGRAPH_NO_WATCH` | Set to `1` to disable the engine's file watcher (slow filesystems like WSL2 `/mnt`). |

## How it works

```text
BioRouter agent
   │ MCP over stdio
   ▼
codegraphagent (Python shim, ~18 KB .brxt)
   ├── install mode (engine not cached)
   │     exposes only codegraphagent_check_engine
   │     downloads engine bundle from this repo's releases
   │
   └── proxy mode (engine cached)
         intercepting MCP proxy:
           ├─ injects codegraphagent_index_project into tools/list
           ├─ handles index_project locally (shells out to engine CLI)
           └─ forwards everything else (codegraph_*) to the engine

   engine subprocess (vendored CodeGraph, Node.js bundled)
   └── owns <project>/.biorouter/codegraph/codegraph.db
       (symlinked from <project>/.codegraph for upstream compatibility)
```

The shim is **pure stdlib Python** — no fastmcp, no httpx, no external deps. The engine is a self-contained Node.js bundle (the engine binary downloads independently on first use, keeping the `.brxt` tiny).

## Status

**v0.1.0** (2026-05-30) — see [CHANGELOG](CHANGELOG.md). 56 Python tests + 1123 engine tests passing.

## Credits

Engine vendored from [CodeGraph](https://github.com/colbymchenry/codegraph)
(MIT, © Colby McHenry). The full upstream license is preserved verbatim at
`engine/LICENSE`. Per-file modifications are documented in
[`engine/PATCHES.md`](engine/PATCHES.md).

R / Julia / MATLAB / Perl extractors use tree-sitter grammars from
[r-lib/tree-sitter-r](https://github.com/r-lib/tree-sitter-r),
[tree-sitter/tree-sitter-julia](https://github.com/tree-sitter/tree-sitter-julia),
[acristoffers/tree-sitter-matlab](https://github.com/acristoffers/tree-sitter-matlab),
and [tree-sitter-perl/tree-sitter-perl](https://github.com/tree-sitter-perl/tree-sitter-perl)
respectively.
