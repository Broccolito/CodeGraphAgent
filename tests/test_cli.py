"""cli.main: cached engine -> proxy; otherwise install shim -> proxy."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codegraphagent import cli
from codegraphagent.errors import BootstrapError


def test_main_proxies_immediately_when_engine_cached(tmp_path: Path):
    cached_launcher = tmp_path / "cached-launcher"
    cached_launcher.write_text("")
    proxy_run = MagicMock(return_value=0)
    install_shim_serve = MagicMock()

    with patch.object(cli.bootstrap, "cached_launcher", return_value=cached_launcher), \
         patch.object(cli.proxy, "run", proxy_run), \
         patch.object(cli.install_shim, "serve", install_shim_serve):
        rc = cli.main()

    assert rc == 0
    install_shim_serve.assert_not_called()
    proxy_run.assert_called_once_with(launcher=cached_launcher)


def test_main_serves_install_shim_then_proxies_with_replayed_initialize(tmp_path: Path):
    installed_launcher = tmp_path / "freshly-installed"
    installed_launcher.write_text("")
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "codegraph_explore"}}
    proxy_run = MagicMock(return_value=0)

    with patch.object(cli.bootstrap, "cached_launcher", return_value=None), \
         patch.object(cli.install_shim, "serve", MagicMock(return_value=(installed_launcher, init, call))), \
         patch.object(cli.proxy, "run", proxy_run):
        rc = cli.main()

    assert rc == 0
    proxy_run.assert_called_once_with(launcher=installed_launcher, replay_initialize=init, pending_call=call)


def test_main_exits_zero_when_install_shim_returns_none():
    proxy_run = MagicMock(return_value=0)
    with patch.object(cli.bootstrap, "cached_launcher", return_value=None), \
         patch.object(cli.install_shim, "serve", MagicMock(return_value=None)), \
         patch.object(cli.proxy, "run", proxy_run):
        assert cli.main() == 0
    proxy_run.assert_not_called()


def test_main_serves_error_shim_on_an_unsupported_platform():
    error_shim_serve = MagicMock()
    with patch.object(cli.bootstrap, "cached_launcher", side_effect=BootstrapError("Unsupported platform")), \
         patch.object(cli.error_shim, "serve", error_shim_serve):
        assert cli.main() == 0
    error_shim_serve.assert_called_once()


def test_main_starts_in_home_with_a_global_codegraph_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """0.1.0 refused to start here: the home folder looked like a project and
    upstream's global ~/.codegraph looked like a conflicting index."""
    home = tmp_path / "home"
    (home / ".codegraph" / "daemons").mkdir(parents=True)
    (home / ".biorouter").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(home))
    monkeypatch.chdir(home)
    launcher = tmp_path / "launcher"
    launcher.write_text("")
    proxy_run = MagicMock(return_value=0)
    error_shim_serve = MagicMock()

    with patch.object(cli.bootstrap, "cached_launcher", return_value=launcher), \
         patch.object(cli.proxy, "run", proxy_run), \
         patch.object(cli.error_shim, "serve", error_shim_serve):
        assert cli.main() == 0

    error_shim_serve.assert_not_called()
    proxy_run.assert_called_once()
    # Nothing was written into the home folder.
    assert sorted(os.listdir(home)) == [".biorouter", ".codegraph"]
    assert not (home / ".codegraph").is_symlink()
