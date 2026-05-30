"""paths.py — project root resolution and layout setup."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codegraphagent import paths
from codegraphagent.errors import LayoutConflictError


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


def test_ensure_layout_creates_biorouter_codegraph_dir(tmp_project: Path):
    paths.ensure_layout(tmp_project)
    assert (tmp_project / ".biorouter" / "codegraph").is_dir()


def test_ensure_layout_creates_symlink(tmp_project: Path):
    paths.ensure_layout(tmp_project)
    link = tmp_project / ".codegraph"
    assert link.is_symlink()
    assert link.resolve() == (tmp_project / ".biorouter" / "codegraph").resolve()


def test_ensure_layout_is_idempotent(tmp_project: Path):
    paths.ensure_layout(tmp_project)
    paths.ensure_layout(tmp_project)
    link = tmp_project / ".codegraph"
    assert link.is_symlink()


def test_ensure_layout_raises_on_real_codegraph_dir(tmp_project: Path):
    (tmp_project / ".codegraph").mkdir()
    with pytest.raises(LayoutConflictError) as excinfo:
        paths.ensure_layout(tmp_project)
    assert excinfo.value.path == str(tmp_project / ".codegraph")


def test_ensure_layout_leaves_existing_symlink_alone(tmp_project: Path):
    paths.ensure_layout(tmp_project)
    link = tmp_project / ".codegraph"
    mtime_before = link.lstat().st_mtime
    paths.ensure_layout(tmp_project)
    mtime_after = link.lstat().st_mtime
    assert mtime_before == mtime_after


def test_ensure_layout_writes_gitignore_for_codegraph_symlink(tmp_project: Path):
    paths.ensure_layout(tmp_project)
    content = (tmp_project / ".gitignore").read_text()
    assert ".codegraph" in content


def test_ensure_layout_does_not_duplicate_gitignore_entry(tmp_project: Path):
    paths.ensure_layout(tmp_project)
    paths.ensure_layout(tmp_project)
    content = (tmp_project / ".gitignore").read_text()
    assert content.count(".codegraph") == 1


def test_ensure_layout_writes_state_dir_gitignore(tmp_project: Path):
    paths.ensure_layout(tmp_project)
    inner = tmp_project / ".biorouter" / "codegraph" / ".gitignore"
    assert inner.exists()
    content = inner.read_text()
    for needle in ("*.db", "*.lock", ".dirty", "cache/"):
        assert needle in content, f"missing {needle!r} in {content}"
