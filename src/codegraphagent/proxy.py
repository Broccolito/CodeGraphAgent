"""Bidirectional stdio piping between BioRouter (parent) and the CodeGraph
engine (child).

The proxy is byte-level: JSON-RPC frames pass through unchanged in both
directions. Two background threads pump bytes; a third drains stderr into the
parent's stderr (which BioRouter logs).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import BinaryIO


_PUMP_CHUNK = 64 * 1024


def _pump(src: BinaryIO, dst: BinaryIO, *, close_dst_on_eof: bool = False) -> None:
    """Copy bytes from src to dst until src is closed/EOF.

    If `close_dst_on_eof` is True, closes dst when src returns EOF — needed for
    the parent_stdin → child_stdin direction so the engine sees EOF and exits
    cleanly when BioRouter closes its end. The child→parent directions leave
    dst open so the parent process can flush other output.
    """
    try:
        while True:
            chunk = src.read(_PUMP_CHUNK)
            if not chunk:
                break
            dst.write(chunk)
            dst.flush()
    except (BrokenPipeError, ValueError):
        # Either side closed; nothing to do.
        pass
    finally:
        if close_dst_on_eof:
            try:
                dst.close()
            except Exception:
                pass


def run(
    *,
    launcher: Path,
    cwd: Path,
    argv_override: list[str] | None = None,
    env_override: dict[str, str] | None = None,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    stderr: BinaryIO | None = None,
) -> int:
    """Spawn the engine and pump stdio between parent and child.

    Args:
        launcher: Path to the engine launcher (or Python interpreter for tests).
        cwd: Working directory for the child (the project root).
        argv_override: Replace the default `["serve", "--mcp"]` argv. Tests
            use this to invoke a fake engine.
        env_override: Additional env vars to pass to the child.
        stdin/stdout/stderr: Override the parent's IO streams (tests use this).

    Returns the child's exit code.
    """
    argv = [str(launcher), *(argv_override or ["serve", "--mcp"])]
    env = {**os.environ}
    if env_override:
        env.update(env_override)

    parent_stdin = stdin or sys.stdin.buffer
    parent_stdout = stdout or sys.stdout.buffer
    parent_stderr = stderr or sys.stderr.buffer

    child = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    threads = [
        threading.Thread(
            target=_pump,
            args=(parent_stdin, child.stdin),
            kwargs={"close_dst_on_eof": True},
            daemon=True,
        ),
        threading.Thread(target=_pump, args=(child.stdout, parent_stdout), daemon=True),
        threading.Thread(target=_pump, args=(child.stderr, parent_stderr), daemon=True),
    ]
    for t in threads:
        t.start()

    rc = child.wait()
    # Wait briefly for the stdout/stderr pumps to finish flushing.
    for t in threads[1:]:
        t.join(timeout=2.0)
    return rc
