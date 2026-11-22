"""Intercepting MCP proxy between Biorouter (parent) and the CodeGraph engine
(child, upstream ``codegraph serve --mcp``).

The proxy parses every JSON-RPC frame so it can:

1. Name the project on each call. Upstream's query tools take an optional
   ``projectPath``; the proxy shows it to the model as ``project_dir`` and maps
   it back (both names are accepted). A call that names no project gets the
   fallback project (``BIOROUTER_WORKING_DIR`` when it is a real project
   folder; see :mod:`codegraphagent.paths`).
2. Add one tool of its own, ``codegraphagent_index_project``, which indexes a
   project with the engine's CLI. Upstream's stance is that indexing is the
   user's decision, so the tool says to call it only when the user asks, and
   it is annotated as a write so Biorouter asks before it runs.
3. Append a short Biorouter note to the server instructions.
4. Replay the client's ``initialize`` to an engine started after the
   handshake (the first-use install path), so the engine is initialized
   before the first request reaches it.

Everything else passes through unchanged in both directions. Tool results are
never rewritten: they carry source code verbatim.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import BinaryIO

from codegraphagent import paths

INDEX_TOOL_NAME = "codegraphagent_index_project"

_PROJECT_DIR_DESCRIPTION = (
    "Absolute path of the project to query (the folder that holds the code, or "
    "any folder inside it): normally the chat's working folder. "
    "Required unless the extension was started with BIOROUTER_WORKING_DIR "
    "pointing at a project."
)

_INDEX_PROJECT_TOOL = {
    "name": INDEX_TOOL_NAME,
    "description": (
        "Build or refresh the CodeGraph index of one project. Call it ONLY when "
        "the user asks to index a project (or agrees when you offer): indexing "
        "is the user's decision. It writes a .codegraph-biorouter/ folder in the "
        "project (kept out of git) and takes about a second for a small project "
        "and up to a few minutes for a large one. The home folder, any folder "
        "above it and the filesystem root are refused. After it succeeds the "
        "codegraph_* tools answer questions about that project."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "project_dir": {
                "type": "string",
                "description": (
                    "Absolute path of the project folder to index (normally the "
                    "chat's working folder)."
                ),
            },
        },
        "required": ["project_dir"],
    },
    "annotations": {
        "title": "Index a project",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}

_INSTRUCTIONS_NOTE = (
    "\n\n## In Biorouter (CodeGraphAgent)\n\n"
    "- Every codegraph_* tool takes `project_dir`: the absolute path of the "
    "project, normally the chat's working folder. Where these instructions or a "
    "tool result say `projectPath`, use `project_dir` (both are accepted).\n"
    "- The index lives in `<project>/.codegraph-biorouter/` rather than "
    "`.codegraph/`. Where a message says to run `codegraph init`, the "
    "Biorouter equivalent is the `codegraphagent_index_project` tool: offer it, "
    "and call it only when the user asks or agrees.\n"
)

# How long an indexing run may take (10 min).
_INDEX_TIMEOUT_SEC = 600.0
# How long to wait for the engine to answer a replayed initialize.
_REPLAY_TIMEOUT_SEC = 60.0
_REPLAY_ID = "codegraphagent-replay-initialize"


def fallback_required(schema: dict) -> dict:
    """Return ``schema`` with ``projectPath`` renamed to ``project_dir``.

    ``project_dir`` stays required only when there is no fallback project.
    """
    props = schema.get("properties")
    if not isinstance(props, dict) or "projectPath" not in props:
        return schema
    new_props = {}
    for key, value in props.items():
        if key == "projectPath":
            prop = dict(value) if isinstance(value, dict) else {"type": "string"}
            prop["description"] = _PROJECT_DIR_DESCRIPTION
            new_props["project_dir"] = prop
        else:
            new_props[key] = value
    required = [r for r in schema.get("required", []) if r != "projectPath"]
    has_fallback = paths.fallback_project() is not None
    if not has_fallback and "project_dir" not in required:
        required.append("project_dir")
    out = dict(schema)
    out["properties"] = new_props
    out["required"] = required
    return out


def rewrite_tools_list(result: dict) -> dict:
    """Rename the project argument on every engine tool and add the index tool."""
    tools = result.get("tools")
    if not isinstance(tools, list):
        return result
    rewritten = []
    for tool in tools:
        if not isinstance(tool, dict):
            rewritten.append(tool)
            continue
        tool = dict(tool)
        schema = tool.get("inputSchema")
        if isinstance(schema, dict):
            tool["inputSchema"] = fallback_required(schema)
        if isinstance(tool.get("description"), str):
            tool["description"] = tool["description"].replace("projectPath", "project_dir")
        rewritten.append(tool)
    if not any(isinstance(t, dict) and t.get("name") == INDEX_TOOL_NAME for t in rewritten):
        rewritten.append(_INDEX_PROJECT_TOOL)
    out = dict(result)
    out["tools"] = rewritten
    return out


def rewrite_initialize(result: dict) -> dict:
    """Append the Biorouter note to the engine's server instructions."""
    out = dict(result)
    instructions = out.get("instructions")
    if isinstance(instructions, str):
        out["instructions"] = instructions.replace("projectPath", "project_dir") + _INSTRUCTIONS_NOTE
    else:
        out["instructions"] = _INSTRUCTIONS_NOTE.strip()
    return out


def map_call_arguments(params: dict) -> dict:
    """Map ``project_dir`` (or the fallback) onto upstream's ``projectPath``."""
    args = params.get("arguments")
    args = dict(args) if isinstance(args, dict) else {}
    raw = args.pop("project_dir", None)
    if raw is not None:
        resolved = paths.resolve_project_dir(raw)
        args["projectPath"] = str(resolved) if resolved is not None else raw
    elif "projectPath" in args:
        resolved = paths.resolve_project_dir(args["projectPath"])
        if resolved is not None:
            args["projectPath"] = str(resolved)
    else:
        fallback = paths.fallback_project()
        if fallback is not None:
            args["projectPath"] = str(fallback)
    out = dict(params)
    out["arguments"] = args
    return out


def is_notification(frame: dict) -> bool:
    return "method" in frame and "id" not in frame


def run(
    *,
    launcher: Path,
    cwd: Path | None = None,
    argv_override: list[str] | None = None,
    env_override: dict[str, str] | None = None,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    stderr: BinaryIO | None = None,
    replay_initialize: dict | None = None,
    pending_call: dict | None = None,
) -> int:
    """Spawn the engine and intercept MCP traffic until the parent's stdin ends.

    Args:
        launcher: Path to the engine launcher (or a Python interpreter in tests).
        cwd: Working folder for the engine. Defaults to an empty run folder, so
            the engine adopts no default project of its own.
        argv_override: Replace ``["serve", "--mcp"]`` (tests).
        env_override: Extra environment for the engine (tests).
        stdin/stdout/stderr: Override the parent streams (tests).
        replay_initialize: The client's ``initialize`` request, when the
            handshake was already answered by the install shim. The engine gets
            it (under a private id) plus ``notifications/initialized`` before
            any other frame.
        pending_call: A request the install shim received but did not answer
            (the call that triggered the engine download); it is handled
            first, exactly as if it had just arrived.

    Returns the engine's exit code.
    """
    workdir = cwd or paths.run_dir()
    argv = [str(launcher), *(argv_override or ["serve", "--mcp"])]
    env = paths.engine_env()
    if env_override:
        env.update(env_override)

    parent_in = stdin or sys.stdin.buffer
    parent_out = stdout or sys.stdout.buffer
    parent_err = stderr or sys.stderr.buffer

    child = subprocess.Popen(
        argv,
        cwd=str(workdir),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    out_lock = threading.Lock()

    def write_parent(frame: dict) -> None:
        with out_lock:
            try:
                parent_out.write((json.dumps(frame) + "\n").encode())
                parent_out.flush()
            except (BrokenPipeError, ValueError, OSError):
                pass

    engine_lock = threading.Lock()

    def write_engine(frame: dict) -> None:
        with engine_lock:
            try:
                child.stdin.write((json.dumps(frame) + "\n").encode())
                child.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                pass

    # Request ids whose responses need rewriting, keyed by what to do.
    pending: dict = {}
    pending_lock = threading.Lock()
    replay_answered: "queue.Queue[dict]" = queue.Queue()

    def engine_reader() -> None:
        for line in iter(child.stdout.readline, b""):
            if not line.strip():
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(frame, dict):
                write_parent(frame)
                continue
            req_id = frame.get("id")
            if req_id == _REPLAY_ID and "method" not in frame:
                replay_answered.put(frame)
                continue
            action = None
            if req_id is not None and "method" not in frame:
                with pending_lock:
                    action = pending.pop(_key(req_id), None)
            result = frame.get("result")
            if action == "tools/list" and isinstance(result, dict):
                frame = {**frame, "result": rewrite_tools_list(result)}
            elif action == "initialize" and isinstance(result, dict):
                frame = {**frame, "result": rewrite_initialize(result)}
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
                except (BrokenPipeError, ValueError, OSError):
                    break
        except (ValueError, AttributeError, OSError):
            pass

    reader = threading.Thread(target=engine_reader, daemon=True)
    drainer = threading.Thread(target=stderr_drainer, daemon=True)
    reader.start()
    drainer.start()

    if replay_initialize is not None:
        replay = dict(replay_initialize)
        replay["id"] = _REPLAY_ID
        write_engine(replay)
        try:
            replay_answered.get(timeout=_REPLAY_TIMEOUT_SEC)
        except queue.Empty:
            _log(parent_err, "engine did not answer the replayed initialize in time")
        write_engine({"jsonrpc": "2.0", "method": "notifications/initialized"})

    index_threads: list[threading.Thread] = []

    def dispatch(req) -> None:
        if not isinstance(req, dict):
            write_engine(req)
            return
        method = req.get("method")
        req_id = req.get("id")
        if method in ("tools/list", "initialize") and req_id is not None:
            with pending_lock:
                pending[_key(req_id)] = method
            write_engine(req)
        elif method == "tools/call":
            params = req.get("params") if isinstance(req.get("params"), dict) else {}
            name = params.get("name", "")
            if name == INDEX_TOOL_NAME:
                # Run in the background so pings and other calls still flow.
                worker = threading.Thread(
                    target=lambda r=req: write_parent(_run_index(r, launcher=launcher)),
                    daemon=True,
                )
                worker.start()
                index_threads.append(worker)
            else:
                write_engine({**req, "params": map_call_arguments(params)})
        else:
            # notifications, ping, responses to engine requests, ...
            write_engine(req)

    try:
        if pending_call is not None:
            dispatch(pending_call)
        for line in iter(parent_in.readline, b""):
            if not line.strip():
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            dispatch(req)
    finally:
        for worker in index_threads:
            worker.join(timeout=_INDEX_TIMEOUT_SEC)
        try:
            child.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass

    try:
        rc = child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        child.terminate()
        try:
            rc = child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            rc = child.wait()
    reader.join(timeout=5)
    drainer.join(timeout=5)
    return rc


def _key(req_id) -> str:
    return json.dumps(req_id, sort_keys=True)


def _log(stream: BinaryIO, message: str) -> None:
    try:
        stream.write(f"[codegraphagent] {message}\n".encode())
        stream.flush()
    except (BrokenPipeError, ValueError, OSError):
        pass


def _run_index(req: dict, *, launcher: Path) -> dict:
    """Handle ``tools/call codegraphagent_index_project``.

    Runs ``codegraph init <dir> --yes --local-only`` the first time and
    ``codegraph index <dir> --quiet`` after that. ``--force`` is never passed,
    so the engine's own refusal of unsafe roots stays in force too.
    """
    req_id = req.get("id")
    params = req.get("params") if isinstance(req.get("params"), dict) else {}
    args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    raw = args.get("project_dir")
    if raw is None:
        raw = args.get("projectPath")
    if raw is None:
        fallback = paths.fallback_project()
        project = fallback
    else:
        project = paths.resolve_project_dir(raw)
    if project is None:
        return _tool_error_response(
            req_id,
            "Pass project_dir: the absolute path of the project folder to index "
            "(normally the chat's working folder).",
        )
    if not project.is_dir():
        return _tool_error_response(req_id, f"{project} is not a folder.")
    reason = paths.unsafe_root_reason(project)
    if reason is not None:
        return _tool_error_response(
            req_id,
            f"Refusing to index {project}: it is {reason}. Pass the folder of "
            "one project instead.",
        )

    state = project / paths.STATE_DIR_NAME
    if (state / "codegraph.db").exists():
        cmd = [str(launcher), "index", str(project), "--quiet"]
    else:
        cmd = [str(launcher), "init", str(project), "--yes", "--local-only"]
    env = paths.engine_env()
    # With the watcher switched off, `init --yes` installs git hooks as its
    # fallback; the index tool never changes a repository's hooks.
    env.pop("CODEGRAPH_NO_WATCH", None)
    env["NO_COLOR"] = "1"
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(project),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=_INDEX_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return _tool_error_response(
            req_id,
            f"Indexing timed out after {_INDEX_TIMEOUT_SEC:.0f}s. The project may "
            "be unusually large.",
        )
    except OSError as exc:
        return _tool_error_response(req_id, f"Could not start the engine to index: {exc}")

    out = completed.stdout.decode(errors="replace").strip()
    err = completed.stderr.decode(errors="replace").strip()
    if completed.returncode != 0:
        body = f"Indexing {project} failed (exit {completed.returncode}).\n"
        if out:
            body += f"Output:\n{out[-1500:]}\n"
        if err:
            body += f"Errors:\n{err[-1500:]}\n"
        return _tool_error_response(req_id, body)

    body = f"Indexed {project}. The codegraph_* tools now answer questions about it (pass project_dir)."
    if out:
        body += f"\n\n{out[-1500:]}"
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": body}], "isError": False},
    }


def _tool_error_response(req_id, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": message}], "isError": True},
    }
