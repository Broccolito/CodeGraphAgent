"""bootstrap.py — engine tarball download + extract + verification."""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codegraphagent import bootstrap
from codegraphagent.errors import BootstrapError


def test_platform_tag_known(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "arm64")
    assert bootstrap.platform_tag() == "darwin-arm64"


def test_platform_tag_linux_x64(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "x86_64")
    assert bootstrap.platform_tag() == "linux-x64"


def test_platform_tag_windows_x64(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Windows")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "AMD64")
    assert bootstrap.platform_tag() == "win32-x64"


def test_platform_tag_unsupported(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "OpenBSD")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "amd64")
    with pytest.raises(BootstrapError):
        bootstrap.platform_tag()


def test_archive_suffix_unix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "linux-x64")
    assert bootstrap.archive_suffix() == "tar.gz"


def test_archive_suffix_windows(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "win32-x64")
    assert bootstrap.archive_suffix() == "zip"


def test_sha256_of_file(tmp_path: Path):
    payload = b"hello, codegraph"
    fp = tmp_path / "blob.bin"
    fp.write_bytes(payload)
    assert bootstrap._sha256_of(fp) == hashlib.sha256(payload).hexdigest()
