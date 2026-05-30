"""Custom exception hierarchy carries enough info to surface MCP-level errors."""

import pytest

from codegraphagent.errors import (
    CodeGraphAgentError,
    LayoutConflictError,
    BootstrapError,
)


def test_layout_conflict_is_codegraphagent_error():
    err = LayoutConflictError("conflict", path="/tmp/x")
    assert isinstance(err, CodeGraphAgentError)
    assert err.path == "/tmp/x"


def test_bootstrap_error_carries_url_and_hashes():
    err = BootstrapError(
        "sha mismatch",
        url="https://example.com/x.tar.gz",
        expected_sha="abc",
        observed_sha="def",
    )
    assert isinstance(err, CodeGraphAgentError)
    assert err.url == "https://example.com/x.tar.gz"
    assert err.expected_sha == "abc"
    assert err.observed_sha == "def"


def test_bootstrap_error_optional_fields_default_to_none():
    err = BootstrapError("plain")
    assert err.url is None
    assert err.expected_sha is None
    assert err.observed_sha is None
