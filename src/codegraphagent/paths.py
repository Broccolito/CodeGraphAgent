"""Project-root resolution and on-disk layout setup.

The CodeGraph engine hardcodes its state directory as `.codegraph/` at the
project root. We want our state under `.biorouter/codegraph/` instead, so we
create the directory in `.biorouter/` and a symlink at `.codegraph` pointing
to it. From the engine's perspective nothing changed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from codegraphagent.errors import LayoutConflictError

_PROJECT_MARKERS = (".biorouter", ".git", "pyproject.toml")


def resolve_project_root() -> Path:
    """Return the absolute path of the project root.

    Order of preference:
    1. $BIOROUTER_WORKING_DIR if set.
    2. The nearest ancestor of CWD containing any of: .biorouter/, .git/,
       pyproject.toml.
    3. CWD as a fallback.
    """
    env = os.environ.get("BIOROUTER_WORKING_DIR")
    if env:
        return Path(env).resolve()

    cwd = Path.cwd().resolve()
    for candidate in [cwd, *cwd.parents]:
        if any((candidate / marker).exists() for marker in _PROJECT_MARKERS):
            return candidate
    return cwd
