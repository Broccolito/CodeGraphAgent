"""cli.main — orchestrates paths → cached_launcher → (install_shim or proxy)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from codegraphagent import cli
from codegraphagent.errors import LayoutConflictError


def test_main_proxies_immediately_when_engine_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Cached engine → straight to proxy, no install_shim involvement."""
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()

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
    proxy_run.assert_called_once()
    kwargs = proxy_run.call_args.kwargs
    assert kwargs["launcher"] == cached_launcher
    assert kwargs["cwd"] == tmp_path.resolve()


def test_main_serves_install_shim_when_not_cached_then_proxies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Not cached → install_shim runs, returns a launcher, then proxy runs."""
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()

    installed_launcher = tmp_path / "freshly-installed"
    installed_launcher.write_text("")

    install_shim_serve = MagicMock(return_value=installed_launcher)
    proxy_run = MagicMock(return_value=0)

    with patch.object(cli.bootstrap, "cached_launcher", return_value=None), \
         patch.object(cli.install_shim, "serve", install_shim_serve), \
         patch.object(cli.proxy, "run", proxy_run):
        rc = cli.main()

    assert rc == 0
    install_shim_serve.assert_called_once()
    proxy_run.assert_called_once()
    assert proxy_run.call_args.kwargs["launcher"] == installed_launcher


def test_main_exits_zero_when_install_shim_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """install_shim returns None (shutdown/EOF before install) → exit 0, no proxy."""
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()

    install_shim_serve = MagicMock(return_value=None)
    proxy_run = MagicMock(return_value=0)

    with patch.object(cli.bootstrap, "cached_launcher", return_value=None), \
         patch.object(cli.install_shim, "serve", install_shim_serve), \
         patch.object(cli.proxy, "run", proxy_run):
        rc = cli.main()

    assert rc == 0
    install_shim_serve.assert_called_once()
    proxy_run.assert_not_called()


def test_main_falls_back_to_error_shim_on_layout_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Real .codegraph directory triggers LayoutConflictError → error_shim."""
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()
    (tmp_path / ".codegraph").mkdir()

    error_shim_serve = MagicMock()
    with patch.object(cli.error_shim, "serve", error_shim_serve):
        rc = cli.main()

    assert rc == 0
    error_shim_serve.assert_called_once()
    assert isinstance(error_shim_serve.call_args.args[0], LayoutConflictError)
