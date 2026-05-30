"""paths.py — project root resolution and layout setup."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codegraphagent import paths


def test_resolve_project_root_uses_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    assert paths.resolve_project_root() == tmp_path.resolve()


def test_resolve_project_root_falls_back_to_cwd_when_env_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("BIOROUTER_WORKING_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.resolve_project_root() == tmp_path.resolve()


def test_resolve_project_root_walks_up_to_git_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    monkeypatch.delenv("BIOROUTER_WORKING_DIR", raising=False)
    monkeypatch.chdir(nested)
    assert paths.resolve_project_root() == tmp_path.resolve()
