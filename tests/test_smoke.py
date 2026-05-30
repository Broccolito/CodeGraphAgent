"""Smoke test: package imports and version is set."""

import codegraphagent


def test_version_is_set():
    assert codegraphagent.__version__ == "0.1.0"


def test_cli_entrypoint_runs(tmp_path, monkeypatch):
    """main() returns 0; full bootstrap is mocked to avoid network I/O."""
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from codegraphagent import cli

    monkeypatch.setenv("BIOROUTER_WORKING_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()

    fake_launcher = tmp_path / "fake-launcher"
    fake_launcher.write_text("")

    with patch.object(cli.bootstrap, "ensure_engine", return_value=fake_launcher), \
         patch.object(cli.proxy, "run", MagicMock(return_value=0)):
        rc = cli.main()

    assert rc == 0
