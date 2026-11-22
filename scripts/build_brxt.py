#!/usr/bin/env python3
"""Build dist/codegraphagent.brxt, dist/codegraphagent-<version>.brxt and dist/SHA256SUMS.

Refuses unless manifest.json, pyproject.toml and src/codegraphagent/__init__.py
name one version, the engine pin has a SHA-256 for every platform, and the
bundle holds manifest.json, README.md, LICENSE, NOTICE, pyproject.toml, uv.lock
and src/. The engine itself is never bundled: it is downloaded from upstream
CodeGraph's release at first use, checked against release_manifest.json.

Usage: python3 scripts/build_brxt.py [--previous <old .brxt>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
NAME = "codegraphagent"
TOP_FILES = ["manifest.json", "README.md", "LICENSE", "NOTICE", "pyproject.toml", "uv.lock"]
EXCLUDE_PARTS = {"__pycache__", "engine", "run", ".pytest_cache"}
# A fixed timestamp keeps the archive byte-for-byte reproducible.
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def fail(message: str) -> None:
    sys.exit(f"build_brxt: {message}")


def versions() -> dict[str, str]:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    init = (ROOT / "src" / NAME / "__init__.py").read_text()
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    return {
        "manifest.json": manifest["version"],
        "pyproject.toml": pyproject["project"]["version"],
        "__init__.py": match.group(1) if match else "",
    }


def check_engine_pin() -> None:
    pin = json.loads((ROOT / "src" / NAME / "release_manifest.json").read_text())
    platforms = pin.get("platforms", {})
    expected = {"darwin-arm64", "darwin-x64", "linux-x64", "linux-arm64", "win32-x64", "win32-arm64"}
    if set(platforms) != expected:
        fail(f"release_manifest.json platforms {sorted(platforms)} != {sorted(expected)}")
    for tag, info in platforms.items():
        if not re.fullmatch(r"[0-9a-f]{64}", info.get("sha256", "")):
            fail(f"release_manifest.json has no SHA-256 for {tag}")
    if not pin.get("base_url", "").startswith("https://github.com/"):
        fail("release_manifest.json base_url must be a GitHub release URL")


def payload() -> list[Path]:
    files = []
    for name in TOP_FILES:
        path = ROOT / name
        if not path.is_file():
            fail(f"missing {name}")
        files.append(path)
    for path in sorted((ROOT / "src").rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if EXCLUDE_PARTS & set(rel.parts) or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        files.append(path)
    return files


def bundled_skill_paths(archive: Path) -> set[str]:
    with zipfile.ZipFile(archive) as zf:
        return {n for n in zf.namelist() if n.startswith("skills/") and n.endswith("SKILL.md")}


def build(previous: Path | None) -> None:
    found = versions()
    if len(set(found.values())) != 1:
        fail(f"versions disagree: {found}")
    version = next(iter(found.values()))
    check_engine_pin()
    files = payload()

    DIST.mkdir(exist_ok=True)
    out = DIST / f"{NAME}.brxt"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())

    names = set(zipfile.ZipFile(out).namelist())
    for required in TOP_FILES + [f"src/{NAME}/cli.py", f"src/{NAME}/release_manifest.json"]:
        if required not in names:
            fail(f"bundle is missing {required}")
    if any("/engine/" in n or n.startswith("engine/") for n in names):
        fail("bundle must not contain an engine")

    if previous is not None:
        missing = bundled_skill_paths(previous) - bundled_skill_paths(out)
        if missing:
            fail(f"bundle drops skill paths of the previous release: {sorted(missing)}")

    versioned = DIST / f"{NAME}-{version}.brxt"
    versioned.write_bytes(out.read_bytes())
    sums = "".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in (out, versioned)
    )
    (DIST / "SHA256SUMS").write_text(sums)
    print(f"wrote {out.name} and {versioned.name} ({out.stat().st_size} bytes, {len(names)} entries)")
    print(sums, end="")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    build(args.previous)


if __name__ == "__main__":
    main()
