# CodeGraphAgent

A [BioRouter](https://github.com/BaranziniLab/BioRouter) extension (`.brxt`)
that provides a pre-indexed code knowledge graph (callers, callees, impact,
trace) via a vendored fork of [CodeGraph](https://github.com/colbymchenry/codegraph).

## What it does

CodeGraphAgent installs into a BioRouter session and exposes 9 MCP tools
(`codegraph_search`, `codegraph_callers`, `codegraph_callees`,
`codegraph_trace`, `codegraph_impact`, `codegraph_node`, `codegraph_explore`,
`codegraph_context`, `codegraph_status`) that let the agent answer "where is X
used?", "what does Y call?", and "what breaks if I change Z?" against the
current project — without re-parsing the codebase on every query.

The index lives at `<project>/.biorouter/codegraph/codegraph.db`. On first
use the extension downloads a vendored CodeGraph engine bundle (~50 MB) from
this repo's GitHub Releases.

## Install

Once a `.brxt` release is published, BioRouter installs the extension via:
`Settings → Extensions → Install from file → codegraphagent.brxt`.

## Status

v0.1.0-rc1 — initial release wrapping upstream CodeGraph unchanged.
See [CHANGELOG](CHANGELOG.md).

## Credits

Engine vendored from [CodeGraph](https://github.com/colbymchenry/codegraph)
(MIT, © Colby McHenry). The full upstream license is at `engine/LICENSE`.
