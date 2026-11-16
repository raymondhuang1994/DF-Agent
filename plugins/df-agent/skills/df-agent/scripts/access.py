#!/usr/bin/env python3
"""Task-scoped write checks and an off-source runtime layout for DF Agent.

Arguments describe authorization already given by the human; they do not prove
consent or replace host/OS access control. No grants or settings are persisted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

DEFAULT_DOCUMENT_ROOT = r"N:\digital finance"
OPERATIONS = frozenset({"setup", "memory", "feedback", "output", "runtime"})
RUNTIME_KINDS = ("indexes", "cache", "logs", "tmp")


class AccessError(ValueError):
    pass


def absolute(path):
    """Normalize without resolving a link or touching the source volume."""
    result = Path(path).expanduser()
    if not result.is_absolute():
        raise AccessError("An explicit absolute path is required.")
    if os.name == "nt":
        raw = str(result)
        if raw.startswith(("\\\\?\\", "\\\\.\\")):
            raise AccessError("Device and extended namespace paths are not supported.")
        for part in result.parts[1:]:
            if part not in {".", ".."} and (part.rstrip(" .") != part or ":" in part):
                raise AccessError("Ambiguous Windows paths and alternate streams are not supported.")
    return Path(os.path.abspath(result))


def under(path, root):
    return path == root or path.is_relative_to(root)


def no_links(path):
    path = absolute(path)
    for entry in [*reversed(path.parents), path]:
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise AccessError("Write paths must not traverse links or reparse points.")
        if entry == path and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise AccessError("Refusing to write a file with multiple hard links.")
    # Windows TEMP may use an 8.3 alias while a store returns its long path.
    # Resolve only after rejecting reparse points, so equivalent safe paths
    # share a boundary without silently following a directory link.
    return path.resolve(strict=False)


def source_roots(document_roots=()):
    # A Windows drive path has no local meaning on POSIX. Never turn it into a
    # relative filename there; explicit native source roots remain protected.
    roots = []
    for raw in document_roots:
        root = absolute(raw)
        roots.append(root)
        if os.name != "nt" or root != absolute(DEFAULT_DOCUMENT_ROOT):
            roots.append(root.resolve(strict=False))
    if os.name == "nt":
        roots.insert(0, absolute(DEFAULT_DOCUMENT_ROOT))
    return tuple(dict.fromkeys(roots))


def check_outside_sources(path, roots, *,grant=False):
    if any(under(path, root) or (grant and under(root, path)) for root in roots):
        raise AccessError("Document sources are read-only; write roots must be separate from them.")


class WriteAccess:
    """Explicit directory/operation scope for one human-authorized task."""

    def __init__(self, task_id, write_roots, operations, document_roots=()):
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 200:
            raise AccessError("A nonempty task ID is required for a write grant.")
        if isinstance(write_roots, (str, bytes, Path)) or isinstance(operations, str):
            raise AccessError("Write roots and operations must be sequences.")
        self.task_id = task_id.strip()
        self.document_roots = source_roots(document_roots)
        self.operations = frozenset(operations)
        if not self.operations or not self.operations <= OPERATIONS:
            raise AccessError("Choose explicit supported write operations.")
        chosen = []
        for raw in write_roots:
            path = absolute(raw)
            if path == Path(path.anchor):
                raise AccessError("A whole drive or filesystem cannot be a write root.")
            check_outside_sources(path, self.document_roots, grant=True)
            resolved = no_links(path)
            check_outside_sources(resolved, self.document_roots, grant=True)
            if resolved.exists() and not resolved.is_dir():
                raise AccessError("A write root must be a directory.")
            chosen.append(path)
        if not chosen:
            raise AccessError("At least one explicit write root is required.")
        self.write_roots = tuple(dict.fromkeys(chosen))

    def require(self, path, operation):
        target = absolute(path)
        check_outside_sources(target, self.document_roots)
        target = no_links(target)
        check_outside_sources(target, self.document_roots)
        if operation not in self.operations:
            raise AccessError(f"Operation '{operation}' has no task-scoped write grant.")
        # Canonicalization can change when a directory is first created in an
        # MSIX virtualized LocalAppData tree. Re-resolve the declared roots on
        # each use rather than pinning an initially nonexistent physical path.
        current_roots = []
        for root in self.write_roots:
            resolved = no_links(root)
            check_outside_sources(resolved, self.document_roots, grant=True)
            current_roots.append(resolved)
        if not any(under(target, root) for root in current_roots):
            raise AccessError("Write target is outside the authorized directories.")
        # Re-check at use time, including grants created before a link appeared.
        return no_links(target)


def require_write(policy, path, operation):
    if policy is None:
        raise AccessError("Read-only by default: confirm task, directory and operation before writing.")
    # The scripts may be imported under different module names by a host. The
    # policy's method owns validation rather than relying on module identity.
    return policy.require(path, operation)


def add_write_arguments(parser):
    parser.add_argument("--task-id", help="Task whose human-approved scope is being used")
    parser.add_argument("--write-root", action="append", default=[], help="Authorized absolute directory; repeatable")
    parser.add_argument("--allow-operation", action="append", choices=sorted(OPERATIONS), default=[])
    parser.add_argument("--document-root", action="append", default=[], help="Additional protected source root; never replaces N:\\digital finance")


def from_args(args):
    if not (args.task_id or args.write_root or args.allow_operation):
        return None
    return WriteAccess(args.task_id, args.write_root, args.allow_operation, args.document_root)


def runtime_layout(runtime_root=None, document_roots=()):
    if runtime_root is None:
        appdata = os.environ.get("LOCALAPPDATA")
        if not appdata:
            raise AccessError("LOCALAPPDATA is unavailable; specify an absolute --runtime-root.")
        runtime_root = Path(appdata) / "DF-Agent" / "runtime"
    root = absolute(runtime_root)
    check_outside_sources(root, source_roots(document_roots), grant=True)
    package = Path(__file__).resolve().parents[3]
    boundaries = [package]
    for parent in package.parents:
        if (parent / ".agents/plugins/marketplace.json").is_file():
            boundaries.append(parent)
            break
    if any(under(root, boundary) or under(boundary, root) for boundary in boundaries):
        raise AccessError("Runtime files must stay outside the plugin and release repository.")
    root = no_links(root)
    check_outside_sources(root, source_roots(document_roots), grant=True)
    if any(under(root, boundary) or under(boundary, root) for boundary in boundaries):
        raise AccessError("Runtime files must stay outside the plugin and release repository.")
    if root.exists() and not root.is_dir():
        raise AccessError("Runtime root must be a directory.")
    paths = {kind: str(no_links(root / kind)) for kind in RUNTIME_KINDS}
    return {"status": "layout", "document_root": DEFAULT_DOCUMENT_ROOT,
            "runtime_root": str(root), "paths": paths, "files_written": False,
            "business_sources_accessed": False, "provider_configured": False}


def prepare_runtime(runtime_root=None, *, write_access=None, document_roots=()):
    effective_sources = [*document_roots, *getattr(write_access, "document_roots", ())]
    result = runtime_layout(runtime_root, effective_sources)
    paths = [Path(value) for value in result["paths"].values()]
    # Validate every destination before creating the first directory.
    for path in paths:
        require_write(write_access, path, "runtime")
        if path.exists() and not path.is_dir():
            raise AccessError("A runtime child path is already a file.")
    created = []
    for path in paths:
        require_write(write_access, path, "runtime")
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        no_links(path)
        if not existed:
            created.append(str(path))
    return {**result, "status": "prepared", "directories_created": created,
            "files_written": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_write_arguments(parser)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("layout", "prepare"):
        sub = commands.add_parser(name)
        sub.add_argument("--runtime-root")
    args = parser.parse_args(argv)
    try:
        policy = from_args(args)
        if args.command == "prepare":
            result = prepare_runtime(args.runtime_root, write_access=policy, document_roots=args.document_root)
        else:
            result = runtime_layout(args.runtime_root, args.document_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (AccessError, OSError, ValueError, TypeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
