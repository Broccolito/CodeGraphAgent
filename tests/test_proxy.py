"""proxy.py — bidirectional stdio piping between BioRouter and the engine."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from codegraphagent import proxy


def test_proxy_run_forwards_stdin_to_child_and_back(tmp_path: Path):
    """Send three JSON-RPC frames into the proxy's stdin, assert the same
    frames come out the proxy's stdout, marked with `proxied: true` by the
    fake engine."""
    parent_in = io.BytesIO(
        b'{"id":1,"method":"initialize"}\n'
        b'{"id":2,"method":"tools/list"}\n'
        b'{"method":"shutdown"}\n'
    )
    parent_out = io.BytesIO()

    # Use the current interpreter to run the fake engine as the "launcher".
    # proxy.run accepts a launcher path + arguments; we override the spawn
    # to use python -m tests.fixtures.fake_engine.
    repo_root = Path(__file__).resolve().parent.parent
    rc = proxy.run(
        launcher=Path(sys.executable),
        cwd=tmp_path,
        argv_override=["-m", "tests.fixtures.fake_engine"],
        env_override={"PYTHONPATH": str(repo_root)},
        stdin=parent_in,
        stdout=parent_out,
        stderr=sys.stderr.buffer,
    )

    assert rc == 0
    lines = [l for l in parent_out.getvalue().decode().splitlines() if l]
    assert len(lines) == 2  # shutdown frame is consumed by the engine
    parsed = [json.loads(l) for l in lines]
    assert parsed[0]["proxied"] is True and parsed[0]["id"] == 1
    assert parsed[1]["proxied"] is True and parsed[1]["id"] == 2


def test_proxy_propagates_child_exit_code(tmp_path: Path):
    parent_in = io.BytesIO(b'{"id":1}\n')
    parent_out = io.BytesIO()
    parent_err = io.BytesIO()

    repo_root = Path(__file__).resolve().parent.parent
    rc = proxy.run(
        launcher=Path(sys.executable),
        cwd=tmp_path,
        argv_override=["-m", "tests.fixtures.fake_engine", "--exit-code", "42"],
        env_override={"PYTHONPATH": str(repo_root)},
        stdin=parent_in,
        stdout=parent_out,
        stderr=parent_err,
    )
    assert rc == 42
