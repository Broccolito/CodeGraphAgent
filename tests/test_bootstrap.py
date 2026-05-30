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


def test_extract_tarball(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "bin").mkdir()
    (src_dir / "bin" / "codegraph").write_text("#!/bin/sh\necho hi\n")
    (src_dir / "lib").mkdir()
    (src_dir / "lib" / "x").write_text("data")

    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(src_dir, arcname=".")

    dest = tmp_path / "extract-to"
    bootstrap._extract(archive, dest)
    assert (dest / "bin" / "codegraph").read_text() == "#!/bin/sh\necho hi\n"
    assert (dest / "lib" / "x").read_text() == "data"


def test_extract_replaces_existing_dest(tmp_path: Path):
    """An existing engine dir is replaced atomically (rename, not in-place rm)."""
    dest = tmp_path / "engine"
    dest.mkdir()
    (dest / "STALE").write_text("old")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "NEW").write_text("new")
    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(src_dir, arcname=".")

    bootstrap._extract(archive, dest)
    assert (dest / "NEW").read_text() == "new"
    assert not (dest / "STALE").exists()


def test_ensure_engine_honors_engine_path_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bundle = tmp_path / "user-bundle"
    bin_dir = bundle / "bin"
    bin_dir.mkdir(parents=True)
    launcher = bin_dir / "codegraph"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    monkeypatch.setenv("CODEGRAPH_ENGINE_PATH", str(bundle))
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "linux-x64")

    result = bootstrap.ensure_engine()
    assert result == launcher


def test_ensure_engine_uses_cached_bundle_with_matching_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "linux-x64")
    monkeypatch.setattr(bootstrap, "_install_dir", lambda: tmp_path / "engine")

    install = tmp_path / "engine"
    (install / "bin").mkdir(parents=True)
    launcher = install / "bin" / "codegraph"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    (install / "VERSION").write_text("0.1.0\n")

    monkeypatch.setattr(
        bootstrap, "_load_manifest",
        lambda: {"engine_version": "0.1.0", "filename": "x", "url": "x", "sha256": "x"},
    )

    download_called = MagicMock()
    monkeypatch.setattr(bootstrap, "_download_and_verify", download_called)

    result = bootstrap.ensure_engine()
    assert result == launcher
    download_called.assert_not_called()


def test_cached_launcher_returns_path_when_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Returns the launcher path when engine is cached and VERSION matches manifest."""
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "linux-x64")
    monkeypatch.setattr(bootstrap, "_install_dir", lambda: tmp_path / "engine")
    monkeypatch.setattr(
        bootstrap, "_load_manifest",
        lambda: {"engine_version": "0.1.0", "filename": "x", "url": "x", "sha256": "x"},
    )

    install = tmp_path / "engine"
    (install / "codegraph-linux-x64" / "bin").mkdir(parents=True)
    launcher = install / "codegraph-linux-x64" / "bin" / "codegraph"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    (install / "VERSION").write_text("0.1.0\n")

    result = bootstrap.cached_launcher()
    assert result == launcher


def test_cached_launcher_returns_none_when_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Returns None when nothing is installed locally."""
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "linux-x64")
    monkeypatch.setattr(bootstrap, "_install_dir", lambda: tmp_path / "engine")
    monkeypatch.setattr(
        bootstrap, "_load_manifest",
        lambda: {"engine_version": "0.1.0", "filename": "x", "url": "x", "sha256": "x"},
    )
    monkeypatch.delenv("CODEGRAPH_ENGINE_PATH", raising=False)

    assert bootstrap.cached_launcher() is None


def test_cached_launcher_returns_none_when_version_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Returns None when installed VERSION differs from manifest's pinned version."""
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "linux-x64")
    monkeypatch.setattr(bootstrap, "_install_dir", lambda: tmp_path / "engine")
    monkeypatch.setattr(
        bootstrap, "_load_manifest",
        lambda: {"engine_version": "0.2.0", "filename": "x", "url": "x", "sha256": "x"},
    )

    install = tmp_path / "engine"
    (install / "codegraph-linux-x64" / "bin").mkdir(parents=True)
    launcher = install / "codegraph-linux-x64" / "bin" / "codegraph"
    launcher.write_text("")
    launcher.chmod(0o755)
    (install / "VERSION").write_text("0.1.0\n")  # stale version

    assert bootstrap.cached_launcher() is None


def test_cached_launcher_honors_engine_path_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If CODEGRAPH_ENGINE_PATH is set, returns its launcher path (skips version check)."""
    bundle = tmp_path / "user-bundle"
    bin_dir = bundle / "codegraph-linux-x64" / "bin"
    bin_dir.mkdir(parents=True)
    launcher = bin_dir / "codegraph"
    launcher.write_text("")
    launcher.chmod(0o755)

    monkeypatch.setenv("CODEGRAPH_ENGINE_PATH", str(bundle))
    monkeypatch.setattr(bootstrap, "platform_tag", lambda: "linux-x64")

    result = bootstrap.cached_launcher()
    assert result == launcher
