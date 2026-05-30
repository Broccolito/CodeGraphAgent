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
