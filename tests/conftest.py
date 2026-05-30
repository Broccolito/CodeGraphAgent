"""Shared pytest fixtures for the codegraphagent test suite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory that looks like a project root.

    Sets BIOROUTER_WORKING_DIR to it so paths.resolve_project_root() finds it
    without walking the real filesystem.
    """
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    # Create a marker so `.git`/pyproject heuristics don't reach into our real repo.
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip CODEGRAPH_* env vars so tests start from a known state."""
    for var in list(os.environ):
        if var.startswith("CODEGRAPH_") or var == "BIOROUTER_WORKING_DIR":
            monkeypatch.delenv(var, raising=False)
    yield
