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


def ensure_layout(root: Path) -> None:
    """Ensure `<root>/.biorouter/codegraph/` exists and `<root>/.codegraph` is
    a symlink pointing at it.

    Idempotent: safe to call repeatedly.

    Raises:
        LayoutConflictError: if `<root>/.codegraph` exists as a real
            directory rather than a symlink.
    """
    state_dir = root / ".biorouter" / "codegraph"
    state_dir.mkdir(parents=True, exist_ok=True)

    link = root / ".codegraph"
    target = Path(".biorouter") / "codegraph"  # relative for portability

    if link.is_symlink():
        return  # idempotent — assume it points where we want
    if link.exists():
        raise LayoutConflictError(
            f"{link} exists as a real directory; "
            "rename or remove it, then restart CodeGraphAgent",
            path=str(link),
        )

    if sys.platform == "win32":
        _create_windows_junction(link, root / target)
    else:
        link.symlink_to(target, target_is_directory=True)


def _create_windows_junction(link: Path, target: Path) -> None:
    """Create a directory junction on Windows (doesn't need admin)."""
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )
