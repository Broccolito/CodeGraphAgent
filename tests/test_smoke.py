"""Smoke test: package imports and version is set."""

import codegraphagent


def test_version_is_set():
    assert codegraphagent.__version__ == "0.1.0"


def test_cli_entrypoint_runs():
    from codegraphagent.cli import main
    rc = main()
    assert rc == 0
