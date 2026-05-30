"""Engine bootstrap — download + verify + extract on first use.

The engine bundle is a per-platform tarball (or .zip on Windows) hosted on our
own GitHub Releases. The release manifest pins both the version and per-platform
SHA256s so a tampered or partial download is detected before we exec it.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import httpx

from codegraphagent.errors import BootstrapError


_PLATFORM_MAP = {
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x64",
    ("Linux", "x86_64"): "linux-x64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Windows", "AMD64"): "win32-x64",
    ("Windows", "ARM64"): "win32-arm64",
}


def platform_tag() -> str:
    """Return the platform tag matching upstream's release asset naming.

    Raises BootstrapError on an unsupported platform.
    """
    key = (platform.system(), platform.machine())
    if key not in _PLATFORM_MAP:
        raise BootstrapError(
            f"Unsupported platform: {key}. "
            f"Supported: {sorted(_PLATFORM_MAP.values())}"
        )
    return _PLATFORM_MAP[key]


def archive_suffix() -> str:
    """Return the archive extension for the current platform."""
    return "zip" if platform_tag().startswith("win32") else "tar.gz"


def _sha256_of(path: Path) -> str:
    """Stream a file through SHA-256 in 64KB chunks. Memory-safe for large
    tarballs (engine bundles are ~50 MB)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> dict:
    """Load the release manifest and resolve the current-platform info.

    Returns dict with keys: engine_version, filename, url, sha256.
    """
    manifest_path = Path(__file__).parent / "release_manifest.json"
    with manifest_path.open() as fh:
        manifest = json.load(fh)

    version = os.environ.get("CODEGRAPH_ENGINE_VERSION") or manifest["engine_version"]
    base_url = manifest["base_url"]
    if os.environ.get("CODEGRAPH_ENGINE_VERSION"):
        # Substitute the version in the URL to the override.
        base_url = (
            f"https://github.com/Broccolito/CodeGraphAgent/releases/"
            f"download/engine-v{version}/"
        )

    tag = platform_tag()
    if tag not in manifest["platforms"]:
        raise BootstrapError(
            f"Manifest does not list a binary for platform {tag}; "
            f"supported: {sorted(manifest['platforms'])}"
        )
    platform_info = manifest["platforms"][tag]
    return {
        "engine_version": version,
        "filename": platform_info["filename"],
        "url": base_url + platform_info["filename"],
        "sha256": platform_info["sha256"],
    }


def _download_and_verify(*, url: str, dest: Path, expected_sha: str) -> None:
    """Stream-download `url` to `dest`, verifying SHA-256 against
    `expected_sha`. On mismatch, removes the partial file and raises
    BootstrapError carrying both hashes.

    A literal "PLACEHOLDER_FILLED_AT_RELEASE" expected_sha skips verification —
    used only during local development before the first release is cut. The
    bypass is logged.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes(64 * 1024):
                        fh.write(chunk)
    except httpx.HTTPError as exc:
        if dest.exists():
            dest.unlink()
        raise BootstrapError(
            f"Engine download failed: {exc}",
            url=url,
        ) from exc

    if expected_sha == "PLACEHOLDER_FILLED_AT_RELEASE":
        import sys
        print(
            f"codegraphagent: skipping SHA verification (placeholder) for {url}",
            file=sys.stderr,
        )
        return

    observed = _sha256_of(dest)
    if observed != expected_sha:
        dest.unlink(missing_ok=True)
        raise BootstrapError(
            "Engine SHA-256 mismatch — refusing to install a tampered or "
            "corrupt bundle. Re-running may help if the download was truncated.",
            url=url,
            expected_sha=expected_sha,
            observed_sha=observed,
        )


def _extract(archive: Path, dest: Path) -> None:
    """Extract `archive` (.tar.gz or .zip) into `dest`, atomically.

    Extracts into a sibling temp dir first, then swaps it into place — so a
    partial extraction can't leave `dest` in a broken half-state.
    """
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".cga-extract-", dir=parent) as staging:
        staging_path = Path(staging)
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(staging_path)
        else:
            with tarfile.open(archive, "r:*") as tf:
                tf.extractall(staging_path)

        if dest.exists():
            old_dest = parent / f".{dest.name}.old"
            if old_dest.exists():
                shutil.rmtree(old_dest)
            dest.rename(old_dest)
            try:
                staging_path.rename(dest)
            except OSError:
                old_dest.rename(dest)
                raise
            shutil.rmtree(old_dest)
        else:
            staging_path.rename(dest)


def _install_dir() -> Path:
    """Return the per-platform install dir inside the extension package."""
    return Path(__file__).parent / "engine"


def _launcher_path(install_dir: Path) -> Path:
    """Return the platform-correct launcher path inside an extracted bundle.

    The tarball extracts with a top-level directory named after the platform
    (e.g. ``codegraph-darwin-arm64/``), so the actual launcher sits at
    ``<install_dir>/codegraph-<tag>/bin/codegraph``.
    """
    tag = platform_tag()
    name = "codegraph.cmd" if tag.startswith("win32") else "codegraph"
    return install_dir / f"codegraph-{tag}" / "bin" / name


def cached_launcher() -> Path | None:
    """Return the launcher path if a matching engine is already installed,
    else None. Read-only — never downloads.

    Order of preference matches ``ensure_engine``:
    1. ``$CODEGRAPH_ENGINE_PATH`` set → return its launcher path (no version check).
    2. Local install dir present and ``VERSION`` matches the pinned manifest →
       return its launcher path.
    3. Otherwise → None.
    """
    override = os.environ.get("CODEGRAPH_ENGINE_PATH")
    if override:
        return _launcher_path(Path(override))

    manifest = _load_manifest()
    install = _install_dir()
    version_file = install / "VERSION"
    if (
        install.exists()
        and version_file.exists()
        and version_file.read_text().strip() == manifest["engine_version"]
    ):
        launcher = _launcher_path(install)
        if launcher.exists():
            return launcher
    return None


def ensure_engine() -> Path:
    """Ensure the engine bundle is present locally and return its launcher.

    Order of preference:
    1. $CODEGRAPH_ENGINE_PATH → use as-is (no download, no verification).
    2. Existing install dir with VERSION matching pinned manifest → reuse.
    3. Download + verify + extract.

    Raises BootstrapError on any failure.
    """
    override = os.environ.get("CODEGRAPH_ENGINE_PATH")
    if override:
        return _launcher_path(Path(override))

    manifest = _load_manifest()
    install = _install_dir()
    version_file = install / "VERSION"
    if (
        install.exists()
        and version_file.exists()
        and version_file.read_text().strip() == manifest["engine_version"]
    ):
        launcher = _launcher_path(install)
        if launcher.exists():
            return launcher

    with tempfile.TemporaryDirectory(prefix=".cga-dl-") as tmp:
        archive = Path(tmp) / manifest["filename"]
        _download_and_verify(
            url=manifest["url"],
            dest=archive,
            expected_sha=manifest["sha256"],
        )
        _extract(archive, install)

    version_file.write_text(manifest["engine_version"] + "\n")
    launcher = _launcher_path(install)
    if not launcher.exists():
        raise BootstrapError(
            f"Extracted bundle is missing the launcher at {launcher}. "
            "The release artifact may be malformed.",
            url=manifest["url"],
        )
    if not launcher.name.endswith(".cmd"):
        launcher.chmod(0o755)
    return launcher
