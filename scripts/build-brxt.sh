#!/usr/bin/env bash
# Build codegraphagent.brxt — a ZIP archive of the .brxt payload.
#
# Excludes:
#   - tests/        (not needed at runtime)
#   - engine/       (the engine is downloaded on first use, not bundled)
#   - .venv/, __pycache__, .pytest_cache, .git
#   - any prior codegraphagent.brxt

set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
OUT="${REPO_ROOT}/codegraphagent.brxt"

rm -f "$OUT"

# zip preserves directory layout; we just include the files the .brxt format requires.
# Critically, exclude src/codegraphagent/engine/ — that's the runtime download
# location populated by bootstrap.ensure_engine(), not part of the .brxt payload.
zip -r "$OUT" \
  manifest.json \
  README.md \
  pyproject.toml \
  src/codegraphagent \
  -x '*/__pycache__/*' '*.pyc' \
     'src/codegraphagent/engine/*' 'src/codegraphagent/engine'

echo
echo "Built: $OUT"
ls -lh "$OUT"
