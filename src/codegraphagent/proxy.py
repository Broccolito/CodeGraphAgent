"""Intercepting MCP proxy between BioRouter (parent) and the CodeGraph
engine (child).

Unlike a byte-level pass-through, this proxy parses every JSON-RPC frame so
it can:
  1. Append our synthetic ``codegraphagent_index_project`` tool to every
     ``tools/list`` response the engine sends.
  2. Handle ``tools/call codegraphagent_index_project`` locally (by shelling
     out to the engine binary as a CLI) instead of forwarding it.

Everything else passes through unchanged in both directions.

Why we own the index tool: upstream's engine doesn't expose indexing as an
MCP tool — it expects ``codegraph init`` to be run from the terminal before
``serve --mcp`` starts. In a BioRouter setting the agent has no terminal,
so the project never gets indexed and queries return "No CodeGraph project
is loaded". Owning a synthetic index tool lets the agent self-serve.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import BinaryIO


_INDEX_PROJECT_TOOL = {
    "name": "codegraphagent_index_project",
    "description": (
        "Build (or rebuild) the CodeGraph index for the current project. "
        "MUST be called once before codegraph_search / codegraph_callers / "
        "codegraph_callees / codegraph_trace / codegraph_impact will return "
        "results — without an index those tools error with 'No CodeGraph "
        "project is loaded'. Re-call after major code changes to refresh "
        "the index. Indexing takes ~1s for tiny projects, up to a few "
        "minutes for monorepos."
    ),
    "inputSchema": {"type": "object", "properties": {}, "required": []},
}

# How long to wait for an indexing subprocess to complete (10 min).
_INDEX_TIMEOUT_SEC = 600.0


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
    """Spawn the engine and intercept MCP traffic.

    Args:
        launcher: Path to the engine launcher (or Python interpreter in tests).
        cwd: Working directory for both the engine child and any subprocess
            we spawn (e.g. for indexing).
        argv_override: Replace ``["serve", "--mcp"]`` for tests.
        env_override: Extra env vars for the engine child.
        stdin/stdout/stderr: Override parent IO streams (tests use this).

    Returns the engine's exit code.
    """
    argv = [str(launcher), *(argv_override or ["serve", "--mcp"])]
    env = {**os.environ}
    if env_override:
        env.update(env_override)

    parent_in = stdin or sys.stdin.buffer
    parent_out = stdout or sys.stdout.buffer
    parent_err = stderr or sys.stderr.buffer

    child = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    # Lock so the parent_out writer is thread-safe (engine_reader thread and
    # the main parent-reading thread both write to parent_out).
    out_lock = threading.Lock()

    def write_parent(frame: dict) -> None:
        with out_lock:
            try:
                parent_out.write((json.dumps(frame) + "\n").encode())
                parent_out.flush()
            except (BrokenPipeError, ValueError):
                pass

    def write_engine(frame: dict) -> None:
        try:
            child.stdin.write((json.dumps(frame) + "\n").encode())
            child.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

    # Set of JSON-RPC request ids that the parent sent as tools/list — when
    # the engine replies with that id, we intercept and append our tool.
    pending_tools_list_ids: set = set()
    pending_lock = threading.Lock()

    def engine_reader() -> None:
        """Read frames from engine.stdout, forwarding to parent. Intercept
        tools/list responses to append our synthetic tool."""
        for line in iter(child.stdout.readline, b""):
            if not line.strip():
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            req_id = frame.get("id")
            with pending_lock:
                intercept = req_id in pending_tools_list_ids
                if intercept:
                    pending_tools_list_ids.discard(req_id)
            if intercept and "result" in frame:
                tools = frame["result"].setdefault("tools", [])
                # Append our tool only if not already present (defense vs replays).
                if not any(t.get("name") == _INDEX_PROJECT_TOOL["name"] for t in tools):
                    tools.append(_INDEX_PROJECT_TOOL)
            write_parent(frame)

    def stderr_drainer() -> None:
        read1 = getattr(child.stderr, "read1", child.stderr.read)
        try:
            while True:
                chunk = read1(64 * 1024)
                if not chunk:
                    break
                try:
                    parent_err.write(chunk)
                    parent_err.flush()
                except (BrokenPipeError, ValueError):
                    break
        except (ValueError, AttributeError):
            pass

    threading.Thread(target=engine_reader, daemon=True).start()
    threading.Thread(target=stderr_drainer, daemon=True).start()

    # Main loop: read from parent, dispatch.
    try:
        for line in iter(parent_in.readline, b""):
            if not line.strip():
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue

            method = req.get("method")
            if method == "tools/list":
                req_id = req.get("id")
                if req_id is not None:
                    with pending_lock:
                        pending_tools_list_ids.add(req_id)
                write_engine(req)
            elif method == "tools/call":
                name = req.get("params", {}).get("name", "")
                if name == _INDEX_PROJECT_TOOL["name"]:
                    write_parent(_run_index(req, launcher=launcher, cwd=cwd))
                else:
                    write_engine(req)
            else:
                # initialize, shutdown, notifications, ping, etc.
                write_engine(req)
    finally:
        # Parent stdin closed (EOF) — close engine stdin so it exits cleanly.
        try:
            child.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass

    rc = child.wait()
    return rc


def _run_index(req: dict, *, launcher: Path, cwd: Path) -> dict:
    """Handle a tools/call codegraphagent_index_project request.

    Picks `init` (first-time) or `index --force` (already initialized) based
    on whether the CodeGraph DB file exists in the project's .codegraph
    directory. Returns the MCP tool-result frame to send back to the parent.
    """
    req_id = req.get("id")
    db_path = cwd / ".codegraph" / "codegraph.db"
    if db_path.exists():
        cmd = [str(launcher), "index", "--force"]
    else:
        cmd = [str(launcher), "init"]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            timeout=_INDEX_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return _tool_error_response(
            req_id,
            f"Indexing timed out after {_INDEX_TIMEOUT_SEC:.0f}s. The project "
            "may be unusually large; try indexing from the CLI directly.",
        )
    except OSError as exc:
        return _tool_error_response(
            req_id,
            f"Could not invoke engine for indexing: {exc}",
        )

    stdout = completed.stdout.decode(errors="replace").strip()
    stderr = completed.stderr.decode(errors="replace").strip()
    if completed.returncode != 0:
        body = (
            f"Indexing failed (exit {completed.returncode}).\n"
            f"Command: {' '.join(cmd[1:])}\n"
        )
        if stdout:
            body += f"stdout:\n{stdout[:1500]}\n"
        if stderr:
            body += f"stderr:\n{stderr[:1500]}\n"
        return _tool_error_response(req_id, body)

    body = "Indexing complete."
    if stdout:
        body += f"\n\n{stdout[:1500]}"
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": body}],
            "isError": False,
        },
    }


def _tool_error_response(req_id, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        },
    }
