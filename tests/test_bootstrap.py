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


def test_load_manifest_returns_pinned_info(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "linux-x64")
    info = bootstrap._load_manifest()
    assert "engine_version" in info
    assert info["filename"] == "codegraph-linux-x64.tar.gz"
    assert info["url"].endswith("codegraph-linux-x64.tar.gz")


def test_load_manifest_respects_engine_version_override(
    monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "linux-x64")
    monkeypatch.setenv("CODEGRAPH_ENGINE_VERSION", "0.9.9")
    info = bootstrap._load_manifest()
    assert "engine-v0.9.9" in info["url"]


def test_download_and_verify_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = b"fake-tarball-bytes-here"
    expected_sha = hashlib.sha256(payload).hexdigest()

    class FakeResponse:
        def __init__(self, content: bytes):
            self._content = content
            self.status_code = 200
        def iter_bytes(self, chunk_size: int = 65536):
            yield self._content
        def raise_for_status(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def stream(self, method, url):
            return FakeResponse(payload)

    monkeypatch.setattr(bootstrap.httpx, "Client", FakeClient)

    dest = tmp_path / "engine.tar.gz"
    bootstrap._download_and_verify(
        url="https://example.com/engine.tar.gz",
        dest=dest,
        expected_sha=expected_sha,
    )
    assert dest.read_bytes() == payload


def test_download_and_verify_sha_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = b"wrong-bytes"

    class FakeResponse:
        def __init__(self):
            self.status_code = 200
        def iter_bytes(self, chunk_size: int = 65536):
            yield payload
        def raise_for_status(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def stream(self, method, url):
            return FakeResponse()

    monkeypatch.setattr(bootstrap.httpx, "Client", FakeClient)

    dest = tmp_path / "engine.tar.gz"
    with pytest.raises(BootstrapError) as excinfo:
        bootstrap._download_and_verify(
            url="https://example.com/engine.tar.gz",
            dest=dest,
            expected_sha="0" * 64,
        )
    assert excinfo.value.observed_sha == hashlib.sha256(payload).hexdigest()
    assert not dest.exists(), "Partial file must be removed on SHA mismatch"
