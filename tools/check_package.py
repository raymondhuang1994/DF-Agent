#!/usr/bin/env python3
"""Validate this entry-only release and create reproducible, reviewed archives.

Standard library only. This checks our release contract, not remote marketplace
acceptance or a complete vendor manifest schema. Never installs anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = Path("plugins/df-agent")
SKILL = PLUGIN / "skills/df-agent"
FORBIDDEN_DIRS = {".venv", "venv", "__pycache__", "node_modules", "private", "validation-local",
                  "runtime", "indexes", "cache", "logs", "tmp"}
FORBIDDEN_NAMES = {".env", ".DS_Store", "auth.json", "credentials.json", "config.local.json",
                   "memory.json", "feedback.json", "memory.lock", ".feedback.lock", ".setup.lock"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def collect(root: Path) -> list[Path]:
    result = []
    for folder, dirs, files in os.walk(root, followlinks=False):
        parent = Path(folder)
        # Git metadata (including a worktree's .git file) is never an artifact.
        dirs[:] = [name for name in dirs if name != ".git"]
        files = [name for name in files if name != ".git"]
        for name in dirs + files:
            path = parent / name
            if is_link(path):
                raise ValueError(f"Release contains a link/reparse point: {path.relative_to(root)}")
            if name in FORBIDDEN_DIRS or name in FORBIDDEN_NAMES or name.endswith(".local.json"):
                raise ValueError(f"Private or generated release entry: {path.relative_to(root)}")
        result.extend(parent / name for name in files)
    return sorted(result, key=lambda p: p.relative_to(root).as_posix())


def require_within(target: Path, base: Path) -> None:
    if not target.resolve().is_relative_to(base.resolve()):
        raise ValueError("A release reference escapes its allowed package root")


def check(root: Path = ROOT) -> tuple[list[Path], list[str], dict]:
    errors: list[str] = []
    try:
        files = collect(root)
    except (OSError, ValueError) as error:
        return [], [str(error)], {}
    manifest = {}
    for path in files:
        rel = path.relative_to(root)
        if path.suffix in {".pyc", ".pyo", ".zip", ".log"}:
            errors.append(f"Generated file in source release: {rel}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"Unexpected binary in this text-only release: {rel}")
            continue
        # Review output should not embed a real user's machine mapping.
        if re.search(r"(?i)[A-Z]:[\\/]+Users[\\/]+(?!<|\{|\$)[A-Za-z0-9_.-]+[\\/]", content):
            errors.append(f"Personal Windows path: {rel}")
        if re.search(r"/(?:Users|home)/[A-Za-z0-9_.-]+/", content):
            errors.append(f"Personal Unix path: {rel}")
        if re.search(r"(?i)(?:sk-proj-|ghp_)[A-Za-z0-9_-]{20,}", content):
            errors.append(f"Credential-like value: {rel}")
        if path.name == "SKILL.md" and ("[TODO:" in content or "TODO: replace" in content):
            errors.append(f"Unfinished skill: {rel}")
        if path.suffix == ".md":
            for raw in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", content):
                link = raw.split("#", 1)[0].strip("<>")
                if not link or "://" in link or link.startswith("mailto:"):
                    continue
                target = (path.parent / link).resolve()
                boundary = root / PLUGIN if rel.is_relative_to(PLUGIN) else root
                try:
                    require_within(target, boundary)
                    if not target.exists():
                        raise ValueError("Missing target")
                except ValueError:
                    errors.append(f"Broken or non-self-contained link: {rel} -> {link}")
    try:
        manifest = json.loads((root / PLUGIN / "plugin.json").read_text("utf-8"))
        compat = json.loads((root / PLUGIN / ".codex-plugin/plugin.json").read_text("utf-8"))
        for field in ("name", "version", "description"):
            if manifest.get(field) != compat.get(field):
                errors.append(f"Manifest mismatch: {field}")
        if manifest.get("name") != "df-agent" or compat.get("skills") != "./skills/":
            errors.append("Unexpected plugin identity or skill root")
        actual = {p.name for p in (root / PLUGIN / "skills").iterdir() if p.is_dir()}
        if actual != {"df-agent"}:
            errors.append(f"Entry release unexpectedly bundles professional skills: {sorted(actual)}")
        skill = (root / SKILL / "SKILL.md").read_text("utf-8")
        front = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", skill, re.S)
        if not front or not re.search(r"(?m)^name:\s*[\"']?df-agent[\"']?\s*$", front.group(1)):
            errors.append("Invalid df-agent frontmatter")
        if not front or not re.search(r"(?m)^description:\s*\S", front.group(1)):
            errors.append("Missing skill description")
        for required in ("agents/openai.yaml", "scripts/doctor.py", "scripts/setup.py", "scripts/setup.ps1",
                         "scripts/memory.py", "scripts/feedback.py", "scripts/access.py", "references/access.md", "references/setup.md",
                         "references/memory.md", "references/quality.md"):
            if not (root / SKILL / required).is_file():
                errors.append(f"Missing entry resource: {required}")
        market = json.loads((root / ".agents/plugins/marketplace.json").read_text("utf-8"))
        entries = market.get("plugins", [])
        if len(entries) != 1 or entries[0].get("name") != manifest["name"]:
            errors.append("Marketplace must contain only this entry plugin")
        else:
            source = entries[0].get("source", {})
            if source.get("source") != "local" or source.get("path") != "./plugins/df-agent":
                errors.append("Unexpected marketplace source")
            else:
                destination = (root / source["path"]).resolve()
                require_within(destination, root)
                if destination != (root / PLUGIN).resolve() or not destination.is_dir():
                    errors.append("Marketplace source not present in repository")
        cases = json.loads((root / "evals/cases.json").read_text("utf-8"))["cases"]
        ids = [case["id"] for case in cases]
        if len(set(ids)) != len(ids):
            errors.append("Duplicate behavioral scenario IDs")
        for case in cases:
            for fixture in case.get("fixtures", []):
                target = (root / "evals" / fixture).resolve()
                require_within(target, root / "evals")
                if not target.is_file():
                    errors.append(f"Missing evaluation fixture: {fixture}")
        sources = json.loads((root / "sources.json").read_text("utf-8"))
        recorded = sources.get("entry_files_sha256", {})
        actual_hashes = {p.relative_to(root / PLUGIN).as_posix(): sha256(p) for p in files if p.is_relative_to(root / PLUGIN)}
        if recorded != actual_hashes:
            errors.append("Entry resource fingerprint inventory is stale; review changes before updating sources.json")
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(f"Invalid or incomplete release metadata: {error}")
    return files, errors, manifest


def archive(destination: Path, files: list[Path], base: Path) -> str:
    destination = destination.absolute()
    if destination.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Archive destination must be outside the development project")
    for parent in [destination, *destination.parents]:
        if parent.exists() and is_link(parent):
            raise ValueError("Archive destination traverses a link/reparse point")
    if destination.exists():
        raise ValueError("Refusing to overwrite an existing archive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in files:
                record = zipfile.ZipInfo(path.relative_to(base).as_posix(), date_time=(2026, 11, 16, 0, 0, 0))
                record.compress_type = zipfile.ZIP_DEFLATED
                record.external_attr = 0o100644 << 16
                bundle.writestr(record, path.read_bytes())
    with zipfile.ZipFile(destination) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("Archive integrity failure")
    return sha256(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, help="Complete repository ZIP outside this project")
    parser.add_argument("--plugin-zip", type=Path, help="Entry plugin ZIP outside this project")
    parser.add_argument("--skill-package", type=Path, help="Root-SKILL.md .skill or ZIP package outside this project")
    args = parser.parse_args()
    files, errors, manifest = check()
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    result = {"status": "passed", "version": manifest["version"], "files": len(files), "scope": "offline_release_contract", "remote_import_tested": False, "archives": []}
    try:
        for destination, base in ((args.zip, ROOT), (args.plugin_zip, ROOT / PLUGIN),
                                  (args.skill_package, ROOT / SKILL)):
            if destination:
                members = [path for path in files if path.is_relative_to(base)]
                digest = archive(destination, members, base)
                result["archives"].append({"name": destination.name, "sha256": digest, "files": len(members)})
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
