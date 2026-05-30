"""cli.main — orchestrates paths.ensure_layout → bootstrap.ensure_engine → proxy.run."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from codegraphagent import cli
from codegraphagent.errors import BootstrapError, LayoutConflictError


def test_main_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()

    fake_launcher = tmp_path / "fake-launcher"
    fake_launcher.write_text("")

    proxy_run = MagicMock(return_value=0)

    with patch.object(cli.bootstrap, "ensure_engine", return_value=fake_launcher), \
         patch.object(cli.proxy, "run", proxy_run):
        rc = cli.main()

    assert rc == 0
    proxy_run.assert_called_once()
    kwargs = proxy_run.call_args.kwargs
    assert kwargs["launcher"] == fake_launcher
    assert kwargs["cwd"] == tmp_path.resolve()


def test_main_falls_back_to_error_shim_on_bootstrap_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()

    err = BootstrapError("nope", url="https://example.com/x")
    error_shim_serve = MagicMock()

    with patch.object(cli.bootstrap, "ensure_engine", side_effect=err), \
         patch.object(cli.error_shim, "serve", error_shim_serve):
        rc = cli.main()

    assert rc == 0
    error_shim_serve.assert_called_once()
    assert error_shim_serve.call_args.args[0] is err


def test_main_falls_back_to_error_shim_on_layout_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()
    (tmp_path / ".codegraph").mkdir()

    error_shim_serve = MagicMock()
    with patch.object(cli.error_shim, "serve", error_shim_serve):
        rc = cli.main()

    assert rc == 0
    error_shim_serve.assert_called_once()
    assert isinstance(error_shim_serve.call_args.args[0], LayoutConflictError)
