#!/usr/bin/env bash
# Sync engine/ with a newer upstream CodeGraph release.
#
# Usage: scripts/sync-upstream.sh <upstream-tag>
#
# Workflow:
#   1. Clone upstream at the target tag into a tmp dir.
#   2. rsync into engine/ (preserving our patches isn't fully automatic —
#      conflicts on files we patched must be resolved by hand in the resulting
#      diff).
#   3. Update engine/UPSTREAM.md with the new tag/SHA.
#   4. Leaves the working tree dirty so the user can review + commit.

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <upstream-tag>"
  exit 64
fi

TAG="$1"
cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

TMP="$(mktemp -d -t cga-sync-XXXXXX)"
trap "rm -rf '$TMP'" EXIT

echo "[1/4] Cloning upstream at $TAG..."
gh repo clone colbymchenry/codegraph "$TMP/upstream" -- --depth 1 --branch "$TAG"

SHA="$(cd "$TMP/upstream" && git rev-parse HEAD)"

echo "[2/4] Syncing into engine/..."
rsync -a --delete \
  --exclude='.git' \
  --exclude='.github' \
  --exclude='node_modules' \
  --exclude='release' \
  --exclude='UPSTREAM.md' \
  --exclude='PATCHES.md' \
  "$TMP/upstream/" engine/

echo "[3/4] Updating engine/UPSTREAM.md..."
DATE="$(date +%Y-%m-%d)"
cat > engine/UPSTREAM.md <<EOF
# Upstream Provenance

This directory is a flat copy of [CodeGraph](https://github.com/colbymchenry/codegraph)
at a pinned commit. We do not preserve upstream's git history here.

| Field | Value |
| --- | --- |
| Upstream repo | https://github.com/colbymchenry/codegraph |
| Vendored tag | $TAG |
| Vendored commit SHA | $SHA |
| Vendored on | $DATE |

## Updating

Run \`scripts/sync-upstream.sh <new-tag>\`. It fetches upstream at the target
tag, syncs into \`engine/\`, and updates this file. Re-apply our patches as
needed (see \`engine/PATCHES.md\`).

## What we change

See \`engine/PATCHES.md\` for the list of modifications layered on top of this
upstream snapshot.
EOF

echo "[4/4] Done. Review with:"
echo "    git status engine/"
echo "    git diff engine/PATCHES.md"
echo
echo "Then re-apply patches per engine/PATCHES.md, run tests, and commit."
