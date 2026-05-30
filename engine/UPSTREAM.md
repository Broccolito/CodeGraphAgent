# Upstream Provenance

This directory is a flat copy of [CodeGraph](https://github.com/colbymchenry/codegraph)
at a pinned commit. We do not preserve upstream's git history here.

| Field | Value |
| --- | --- |
| Upstream repo | https://github.com/colbymchenry/codegraph |
| Vendored tag | v0.9.7 |
| Vendored commit SHA | f29825c090f37ee629cade6d9cae9821461dcd14 |
| Vendored on | 2026-05-30 |

## Updating

To pull in newer upstream changes, run `scripts/sync-upstream.sh` (added in
Phase G). It fetches upstream at a target tag, three-way merges into `engine/`,
and updates this file with the new SHA. Conflicts surface as a normal PR.

## What we change

See `engine/PATCHES.md` for the list of modifications layered on top of this
upstream snapshot.
