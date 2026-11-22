"""Which project a call is about, and the folders the shim uses.

A stdio extension is never told which folder the chat is working in, so the
project comes from each tool call's ``project_dir`` argument. When a call
leaves it out, the shim falls back to ``BIOROUTER_WORKING_DIR``, but only when
that variable is set and names a real project folder: never the home folder,
a folder above it, or a filesystem root.

The engine keeps each project's index in ``<project>/.codegraph-biorouter/``
(upstream's ``CODEGRAPH_DIR`` setting). That name cannot collide with a
project's own ``.codegraph/`` index or with upstream CodeGraph's global
``~/.codegraph`` folder, and upstream skips every ``.codegraph-*`` folder when
it indexes or watches a tree.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# The per-project index folder name handed to the engine as CODEGRAPH_DIR.
STATE_DIR_NAME = ".codegraph-biorouter"


def _canonical(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()


def _fold(path: Path) -> str:
    text = str(path)
    if sys.platform in ("win32", "darwin"):
        return text.lower()
    return text


def home_dir() -> Path:
    return _canonical(Path.home())


def unsafe_root_reason(path: Path) -> str | None:
    """Return why ``path`` must never be a project root, or None if it may be.

    Mirrors upstream's own refusal: the filesystem root, the home folder and
    any folder above the home folder.
    """
    resolved = _canonical(path)
    if resolved.parent == resolved:
        return "the filesystem root"
    home = home_dir()
    if _fold(resolved) == _fold(home):
        return "your home folder"
    if _fold(home).startswith(_fold(resolved) + os.sep):
        return "a folder above your home folder"
    return None


def fallback_project() -> Path | None:
    """The project a call that names none falls back to, or None.

    ``BIOROUTER_WORKING_DIR`` counts only when it is set, is a directory and is
    not an unsafe root (see :func:`unsafe_root_reason`).
    """
    raw = os.environ.get("BIOROUTER_WORKING_DIR", "").strip()
    if not raw:
        return None
    path = _canonical(Path(raw))
    if not path.is_dir():
        return None
    if unsafe_root_reason(path) is not None:
        return None
    return path


def resolve_project_dir(raw: object) -> Path | None:
    """Turn a tool call's ``project_dir`` value into an absolute path.

    ``~`` is expanded. A relative value is taken against the fallback project
    when there is one; with no fallback it cannot be resolved and None is
    returned. An empty or non-string value also returns None.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw.strip()).expanduser()
    if not path.is_absolute():
        base = fallback_project()
        if base is None:
            return None
        path = base / path
    return _canonical(path)


def run_dir() -> Path:
    """An empty folder the engine runs in.

    The engine is started outside every project so it never adopts a default
    project of its own: each call names its project (or the shim fills in the
    fallback). The folder lives inside the extension when it is writable, else
    in the temporary folder.
    """
    candidates = [Path(__file__).parent / "run", Path(tempfile.gettempdir()) / "codegraphagent-run"]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path(tempfile.mkdtemp(prefix="codegraphagent-run-"))


def engine_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment the engine child runs with.

    Telemetry and the update check are always off, and the index folder name is
    always :data:`STATE_DIR_NAME`, whatever the parent environment says. The
    tool list defaults to upstream's documented four-tool surface; a user's own
    ``CODEGRAPH_MCP_TOOLS`` wins.
    """
    env = dict(os.environ if base is None else base)
    env["CODEGRAPH_TELEMETRY"] = "0"
    env["DO_NOT_TRACK"] = "1"
    env["CODEGRAPH_NO_UPDATE_CHECK"] = "1"
    env["CODEGRAPH_DIR"] = STATE_DIR_NAME
    if not env.get("CODEGRAPH_MCP_TOOLS", "").strip():
        env["CODEGRAPH_MCP_TOOLS"] = "explore,node,search,callers"
    return env
