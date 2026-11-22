"""paths: project resolution, unsafe roots and the engine environment."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraphagent import paths


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: home))
    return home


def test_home_and_parents_and_root_are_unsafe(fake_home: Path):
    assert paths.unsafe_root_reason(fake_home) == "your home folder"
    assert paths.unsafe_root_reason(fake_home.parent) == "a folder above your home folder"
    assert paths.unsafe_root_reason(Path("/")) == "the filesystem root"


def test_a_project_under_home_is_safe(fake_home: Path):
    project = fake_home / "proj"
    project.mkdir()
    assert paths.unsafe_root_reason(project) is None


def test_fallback_unset_is_none(clean_env, fake_home: Path):
    assert paths.fallback_project() is None


def test_fallback_is_working_dir_when_it_is_a_project(clean_env, fake_home: Path, monkeypatch):
    project = fake_home / "proj"
    project.mkdir()
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(project))
    assert paths.fallback_project() == project.resolve()


def test_fallback_ignores_home(clean_env, fake_home: Path, monkeypatch):
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(fake_home))
    assert paths.fallback_project() is None


def test_fallback_ignores_a_missing_folder(clean_env, fake_home: Path, monkeypatch):
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(fake_home / "gone"))
    assert paths.fallback_project() is None


def test_resolve_project_dir_absolute_and_tilde(clean_env, fake_home: Path, monkeypatch):
    project = fake_home / "proj"
    project.mkdir()
    assert paths.resolve_project_dir(str(project)) == project.resolve()
    monkeypatch.setattr(paths.Path, "expanduser", lambda self: Path(str(self).replace("~", str(fake_home), 1)))
    assert paths.resolve_project_dir("~/proj") == project.resolve()


def test_resolve_project_dir_relative_needs_a_fallback(clean_env, fake_home: Path, monkeypatch):
    project = fake_home / "proj"
    (project / "sub").mkdir(parents=True)
    assert paths.resolve_project_dir("sub") is None
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(project))
    assert paths.resolve_project_dir("sub") == (project / "sub").resolve()


def test_resolve_project_dir_rejects_non_strings():
    assert paths.resolve_project_dir(None) is None
    assert paths.resolve_project_dir("  ") is None
    assert paths.resolve_project_dir(3) is None


def test_engine_env_forces_telemetry_off_and_the_state_dir(clean_env):
    env = paths.engine_env({"CODEGRAPH_TELEMETRY": "1", "CODEGRAPH_DIR": ".codegraph", "DO_NOT_TRACK": "0"})
    assert env["CODEGRAPH_TELEMETRY"] == "0"
    assert env["DO_NOT_TRACK"] == "1"
    assert env["CODEGRAPH_NO_UPDATE_CHECK"] == "1"
    assert env["CODEGRAPH_DIR"] == paths.STATE_DIR_NAME == ".codegraph-biorouter"
    assert env["CODEGRAPH_MCP_TOOLS"] == "explore,node,search,callers"


def test_engine_env_keeps_a_users_tool_list(clean_env):
    env = paths.engine_env({"CODEGRAPH_MCP_TOOLS": "explore"})
    assert env["CODEGRAPH_MCP_TOOLS"] == "explore"


def test_state_dir_cannot_be_the_global_codegraph_folder():
    # Upstream keeps its global state in ~/.codegraph; the index folder must
    # never share that name, even for a project at the home folder.
    assert paths.STATE_DIR_NAME != ".codegraph"
    assert paths.STATE_DIR_NAME.startswith(".codegraph-")


def test_run_dir_is_an_empty_existing_folder():
    run = paths.run_dir()
    assert run.is_dir()
