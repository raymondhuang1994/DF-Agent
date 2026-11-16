#!/usr/bin/env python3
"""Local reviewed memory. Explicit scope; no network, chat collection, or scheduling.

Memory is reference material, never a grant of execution permission. Each content
version has its own ID. Revision history contains ID sets, not duplicate payloads.
"""
from __future__ import annotations

import sys

# Read commands must not create imported-module caches in the plugin either.
sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

if "df_agent_write_access" not in sys.modules:
    _ACCESS_SPEC = importlib.util.spec_from_file_location("df_agent_write_access", Path(__file__).with_name("access.py"))
    _ACCESS_MODULE = importlib.util.module_from_spec(_ACCESS_SPEC)
    sys.modules["df_agent_write_access"] = _ACCESS_MODULE
    _ACCESS_SPEC.loader.exec_module(_ACCESS_MODULE)
access = sys.modules["df_agent_write_access"]


class MemoryError(ValueError):
    """An invalid request, scope mismatch, or unsafe local state."""


KINDS = {"preference", "decision", "definition", "lesson", "accepted_example", "fact"}
PROVENANCE_KINDS = {"user_feedback", "user_instruction", "artifact", "document", "synthetic"}
STATUSES = {"candidate", "published", "superseded", "withdrawn"}
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
MAX_FILE_BYTES = 32 * 1024 * 1024


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def timestamp(value, name="timestamp") -> datetime:
    if not isinstance(value, str):
        raise MemoryError(f"{name} must be a timezone-aware ISO8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemoryError(f"Invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MemoryError(f"{name} requires an explicit timezone")
    return parsed.astimezone(timezone.utc)


def string(value, name, maximum=128):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise MemoryError(f"{name} must be nonempty text of at most {maximum} characters")
    return value.strip()


def identity(value, name="id"):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise MemoryError(f"{name} requires 1-64 ASCII letters, digits, dots, hyphens or underscores")
    return value


def strings(value, name, maximum=20, item_max=128, identifiers=False):
    if not isinstance(value, list) or len(value) > maximum:
        raise MemoryError(f"{name} must be a list with at most {maximum} items")
    result = [identity(item, name) if identifiers else string(item, name, item_max) for item in value]
    if len(set(result)) != len(result):
        raise MemoryError(f"{name} contains duplicate values")
    return result


def context(scope, owner, project=None):
    if not isinstance(scope, str) or scope not in {"personal", "project"}:
        raise MemoryError("scope must be personal or project; team publishing is not supported")
    owner = string(owner, "owner")
    if scope == "project":
        project = string(project, "project", 160)
    elif project is not None:
        raise MemoryError("Personal memories cannot have a project field; use tags for task context")
    return scope, owner, project


def record_context(record):
    return record["scope"], record["owner"], record.get("project")


def conflict_key(record):
    return (*record_context(record), record["key"])


def validate_candidate(data):
    if not isinstance(data, dict):
        raise MemoryError("Candidate input must be a JSON object")
    required = {"id", "scope", "owner", "key", "content", "provenance"}
    allowed = required | {"project", "kind", "tags", "feedback_ids", "supersedes", "expires_at"}
    if required - data.keys() or data.keys() - allowed:
        raise MemoryError("Candidate input has missing or unknown fields")
    result = deepcopy(data)
    result["id"] = identity(data["id"])
    scope, owner, project = context(data["scope"], data["owner"], data.get("project"))
    result.update(scope=scope, owner=owner)
    if project is None:
        result.pop("project", None)
    else:
        result["project"] = project
    result["key"] = string(data["key"], "key", 160)
    result["content"] = string(data["content"], "content", 12000)
    result["kind"] = data.get("kind", "lesson")
    if not isinstance(result["kind"], str) or result["kind"] not in KINDS:
        raise MemoryError("Unknown memory kind")
    for field in ("tags", "feedback_ids", "supersedes"):
        result[field] = strings(data.get(field, []), field, identifiers=field in {"feedback_ids", "supersedes"})
    if result["id"] in result["supersedes"]:
        raise MemoryError("A memory cannot supersede itself")
    provenance = data["provenance"]
    if not isinstance(provenance, list) or not 1 <= len(provenance) <= 20:
        raise MemoryError("provenance must contain 1-20 source records")
    normalized = []
    for item in provenance:
        fields = {"source", "locator", "version", "observed_at"}
        if not isinstance(item, dict) or fields - item.keys() or item.keys() - (fields | {"kind"}):
            raise MemoryError("Provenance requires source, locator, version and observed_at")
        entry = {name: string(item[name], f"provenance.{name}", 2048 if name in {"source", "locator"} else 256)
                 for name in ("source", "locator", "version")}
        timestamp(item["observed_at"], "provenance.observed_at")
        entry["observed_at"] = item["observed_at"]
        if "kind" in item:
            if not isinstance(item["kind"], str) or item["kind"] not in PROVENANCE_KINDS:
                raise MemoryError("Unknown provenance kind")
            entry["kind"] = item["kind"]
        normalized.append(entry)
    result["provenance"] = normalized
    if "expires_at" in data:
        timestamp(data["expires_at"], "expires_at")
    elif result["kind"] == "fact":
        raise MemoryError("Facts require expires_at; recheck volatile facts at use time")
    return result


def no_links(path: Path):
    """Reject Windows junctions as well as symbolic links in existing ancestors."""
    for entry in [path, *path.parents]:
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise MemoryError("Memory path traverses a link or reparse point")


def read_json(path: Path):
    # Read one opened file, so an atomic replacement cannot mix revisions.
    with path.open("rb") as handle:
        if os.fstat(handle.fileno()).st_size > MAX_FILE_BYTES:
            raise MemoryError("JSON file exceeds the 32 MiB store/input limit")
        payload = handle.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise MemoryError("JSON file exceeds the 32 MiB store/input limit")
    try:
        return json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MemoryError("Invalid UTF-8 JSON") from exc


def validate_state(state):
    if not isinstance(state, dict) or set(state) != {"schema_version", "revision", "records", "events", "tombstones"}:
        raise MemoryError("Invalid memory store structure")
    if type(state["schema_version"]) is not int or state["schema_version"] != 1 or type(state["revision"]) is not int or state["revision"] < 0:
        raise MemoryError("Unsupported memory store version or revision")
    if not isinstance(state["records"], dict) or not isinstance(state["events"], list):
        raise MemoryError("Invalid records or revision history")
    tombstones = strings(state["tombstones"], "tombstones", maximum=100000, identifiers=True)
    current_keys = set()
    for rid, record in state["records"].items():
        identity(rid)
        if not isinstance(record, dict) or record.get("id") != rid or rid in tombstones:
            raise MemoryError("Invalid record identity")
        meta = {"status", "created_at", "review", "superseded_by"}
        stored_candidate = {key: value for key, value in record.items() if key not in meta}
        candidate = validate_candidate(stored_candidate)
        if candidate != stored_candidate:
            raise MemoryError("Record fields are not normalized")
        if not isinstance(record.get("status"), str) or record["status"] not in STATUSES:
            raise MemoryError("Invalid record status")
        timestamp(record.get("created_at"), "created_at")
        review = record.get("review")
        if review is not None:
            if not isinstance(review, dict) or set(review) != {"reviewer", "reason", "reviewed_at"}:
                raise MemoryError("Invalid memory review")
            string(review["reviewer"], "reviewer")
            string(review["reason"], "reason", 2000)
            timestamp(review["reviewed_at"], "reviewed_at")
        if record["status"] != "candidate" and review is None:
            raise MemoryError("Published history lacks a review")
        if "superseded_by" in record:
            identity(record["superseded_by"], "superseded_by")
        if record["status"] == "published":
            key = conflict_key(record)
            if key in current_keys:
                raise MemoryError("Conflicting current published memories")
            current_keys.add(key)
    if len(state["events"]) != state["revision"] + 1:
        raise MemoryError("Revision history is incomplete")
    for revision, event in enumerate(state["events"]):
        if not isinstance(event, dict) or type(event.get("revision")) is not int or event["revision"] != revision:
            raise MemoryError("Noncontiguous revision history")
        required_event = {"revision", "action", "at", "ids", "published_ids"}
        if required_event - event.keys() or set(event) - (required_event | {"actor", "reason_sha256", "target_revision"}):
            raise MemoryError("Unknown revision metadata")
        timestamp(event.get("at"), "event timestamp")
        if not isinstance(event.get("action"), str) or event["action"] not in {"init", "candidate", "publish", "rollback", "delete"}:
            raise MemoryError("Unknown revision action")
        ids = strings(event.get("ids"), "event IDs", maximum=100000, identifiers=True)
        published = strings(event.get("published_ids"), "published IDs", maximum=100000, identifiers=True)
        if set(ids) - state["records"].keys() or set(published) - state["records"].keys():
            raise MemoryError("Revision references a missing/deleted record")
        if "actor" in event:
            string(event["actor"], "actor")
        if "reason_sha256" in event and (not isinstance(event["reason_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", event["reason_sha256"])):
            raise MemoryError("Invalid audit reason digest")
        if "target_revision" in event and (type(event["target_revision"]) is not int or not 0 <= event["target_revision"] < revision):
            raise MemoryError("Invalid rollback target revision")
    current = sorted(rid for rid, record in state["records"].items() if record["status"] == "published")
    if state["events"][-1]["published_ids"] != current:
        raise MemoryError("Current records do not match the latest revision")
    return state


class MemoryStore:
    def __init__(self, directory, lock_timeout=5.0, *, write_access=None):
        self.directory = Path(directory)
        if not self.directory.is_absolute():
            raise MemoryError("--store must be an explicit absolute directory outside the plugin/repository")
        no_links(self.directory)
        self.directory = self.directory.resolve()
        plugin = Path(__file__).resolve().parents[3]
        repo = Path(__file__).resolve().parents[5]
        boundaries = [plugin]
        if (repo / ".agents/plugins/marketplace.json").exists():
            boundaries.append(repo)
        if any(self.directory.is_relative_to(boundary) for boundary in boundaries):
            raise MemoryError("Memory storage must be outside the plugin and source repository")
        if not isinstance(lock_timeout, (int, float)) or not 0 <= lock_timeout <= 60:
            raise MemoryError("lock_timeout must be between 0 and 60 seconds")
        self.lock_timeout = lock_timeout
        self.path = self.directory / "memory.json"
        self.write_access = write_access

    @contextmanager
    def _locked(self, create=False):
        access.require_write(self.write_access, self.directory, "memory")
        access.require_write(self.write_access, self.path, "memory")
        no_links(self.directory)
        if create:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.directory.is_dir():
            raise MemoryError("Store does not exist; run init first")
        no_links(self.directory)
        lock_path = self.directory / "memory.lock"
        no_links(lock_path)
        access.require_write(self.write_access, lock_path, "memory")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        locked = False
        try:
            with os.fdopen(descriptor, "r+b", buffering=0) as handle:
                info = os.fstat(handle.fileno())
                if info.st_nlink > 1:
                    raise MemoryError("Memory lock must not share a hard link with another file")
                if info.st_size == 0:
                    handle.write(b"0")
                start = time.monotonic()
                while True:
                    try:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except OSError as exc:
                        if time.monotonic() - start >= self.lock_timeout:
                            raise MemoryError("Memory store is busy; retry after the active operation finishes") from exc
                        time.sleep(0.05)
                try:
                    no_links(self.path)
                    yield
                finally:
                    if locked:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise MemoryError("Unable to lock or access the memory store") from exc

    def _load(self):
        no_links(self.directory)
        no_links(self.path)
        if not self.path.is_file():
            raise MemoryError("Store is not initialized; run init first")
        return validate_state(read_json(self.path))

    def _write(self, state):
        access.require_write(self.write_access, self.path, "memory")
        validate_state(state)
        payload = (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if len(payload) > MAX_FILE_BYTES:
            raise MemoryError("Store exceeds 32 MiB; reduce retained memories before retrying")
        temporary = self.directory / f".memory-{uuid.uuid4().hex}.tmp"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            # Windows readers can briefly deny replacement while holding an
            # ordinary read-only handle. Retry only the atomic replace, while
            # retaining the writer lock and the already validated snapshot.
            deadline = time.monotonic() + min(self.lock_timeout, 2.0)
            while True:
                access.require_write(self.write_access, self.path, "memory")
                try:
                    os.replace(temporary, self.path)
                    break
                except OSError as exc:
                    remaining = deadline - time.monotonic()
                    if os.name != "nt" or getattr(exc, "winerror", None) not in {5, 32, 33} or remaining <= 0:
                        raise
                    time.sleep(min(0.025, remaining))
        finally:
            if temporary.exists():
                temporary.unlink()

    def _commit(self, state, action, ids, actor=None, reason=None, target_revision=None):
        state["revision"] += 1
        event = {"revision": state["revision"], "action": action, "at": utcnow(), "ids": sorted(ids),
                 "published_ids": sorted(rid for rid, record in state["records"].items() if record["status"] == "published")}
        if actor:
            event["actor"] = actor
        if reason:
            # Audit reasons may quote deleted content, so history stores only a digest.
            event["reason_sha256"] = hashlib.sha256(reason.encode("utf-8")).hexdigest()
        if target_revision is not None:
            event["target_revision"] = target_revision
        state["events"].append(event)
        self._write(state)
        return {"status": action, "revision": state["revision"], "ids": sorted(ids)}

    def init(self):
        with self._locked(create=True):
            if self.path.exists():
                raise MemoryError("Store already exists; initialization never overwrites it")
            state = {"schema_version": 1, "revision": 0, "records": {}, "tombstones": [],
                     "events": [{"revision": 0, "action": "init", "at": utcnow(), "ids": [], "published_ids": []}]}
            self._write(state)
            return {"status": "initialized", "revision": 0}

    def candidate(self, data):
        record = validate_candidate(data)
        with self._locked():
            state = self._load()
            rid = record["id"]
            if rid in state["records"] or rid in state["tombstones"]:
                raise MemoryError("Memory ID already used; use a new ID for a new content version")
            for old_id in record["supersedes"]:
                old = state["records"].get(old_id)
                if not old or old["status"] != "published" or conflict_key(old) != conflict_key(record):
                    raise MemoryError("supersedes must identify current published memories with exactly the same scope and key")
            record.update(status="candidate", created_at=utcnow())
            state["records"][rid] = record
            return self._commit(state, "candidate", [rid])

    @staticmethod
    def _find(state, rid, owner, project=None):
        identity(rid)
        owner = string(owner, "owner")
        if project is not None:
            project = string(project, "project", 160)
        record = state["records"].get(rid)
        if not record or record["owner"] != owner or record.get("project") != project:
            raise MemoryError("Memory is absent or outside the requested owner/project scope")
        return record

    @staticmethod
    def _review(reviewer, reason, approve):
        if approve is not True:
            raise MemoryError("Explicit --approve is required after reviewing this concrete change")
        return string(reviewer, "reviewer"), string(reason, "reason", 2000)

    def publish(self, rid, owner, reviewer, reason, approve=False, project=None):
        reviewer, reason = self._review(reviewer, reason, approve)
        with self._locked():
            state = self._load()
            record = self._find(state, rid, owner, project)
            if record["status"] != "candidate":
                raise MemoryError("Only candidates can be published; create a new candidate for an update")
            if record.get("expires_at") and timestamp(record["expires_at"]) <= timestamp(utcnow()):
                raise MemoryError("Expired candidates cannot be published")
            conflicts = sorted(old_id for old_id, old in state["records"].items()
                               if old["status"] == "published" and conflict_key(old) == conflict_key(record))
            if sorted(record["supersedes"]) != conflicts:
                raise MemoryError("Published memory conflicts with this key, or supersession is stale; review a fresh candidate")
            for old_id in conflicts:
                state["records"][old_id].update(status="superseded", superseded_by=rid)
            record.update(status="published", review={"reviewer": reviewer, "reason": reason, "reviewed_at": utcnow()})
            return self._commit(state, "publish", [rid, *conflicts], reviewer, reason)

    def retrieve(self, owner, project=None, query=None, limit=20, scope=None, now=None, status="published"):
        owner = string(owner, "owner")
        if project is not None:
            project = string(project, "project", 160)
        if scope not in {None, "personal", "project"} or (scope == "project" and project is None):
            raise MemoryError("A project scope requires project; unknown scopes are rejected")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MemoryError("limit must be between 1 and 100")
        if status not in STATUSES | {"all"}:
            raise MemoryError("Unknown status filter")
        tokens = [] if query is None else string(query, "query", 500).casefold().split()
        at = timestamp(now or utcnow())
        state = self._load()
        found = []
        for record in state["records"].values():
            if record["owner"] != owner:
                continue
            if record["scope"] == "project" and (project is None or record["project"] != project):
                continue
            if scope is not None and record["scope"] != scope:
                continue
            if status != "all" and record["status"] != status:
                continue
            expired = bool(record.get("expires_at") and timestamp(record["expires_at"]) <= at)
            if status == "published" and expired:
                continue
            haystack = " ".join([record["key"], record["content"], *record["tags"]]).casefold()
            score = sum(token in haystack for token in tokens)
            if tokens and score == 0:
                continue
            item = deepcopy(record)
            item["expired"] = expired
            found.append((score, item))
        found.sort(key=lambda pair: (-pair[0], pair[1]["key"], pair[1]["id"]))
        return {"status": "ok", "revision": state["revision"], "reference_only": True,
                "total_matches": len(found), "records": [item for _, item in found[:limit]]}

    def rollback(self, revision, scope, owner, reviewer, reason, approve=False, project=None):
        reviewer, reason = self._review(reviewer, reason, approve)
        selected_context = context(scope, owner, project)
        with self._locked():
            state = self._load()
            if type(revision) is not int or not 0 <= revision <= state["revision"]:
                raise MemoryError("Unknown rollback revision")
            selected = {rid for rid in state["events"][revision]["published_ids"]
                        if record_context(state["records"][rid]) == selected_context}
            affected = []
            for rid, record in state["records"].items():
                if record_context(record) != selected_context or record["status"] == "candidate":
                    continue
                record["status"] = "published" if rid in selected else "withdrawn"
                record.pop("superseded_by", None)
                affected.append(rid)
            return self._commit(state, "rollback", affected, reviewer, reason, revision)

    def delete(self, rid, owner, reason, approve=False, project=None):
        _, reason = self._review(owner, reason, approve)
        with self._locked():
            state = self._load()
            self._find(state, rid, owner, project)
            del state["records"][rid]
            state["tombstones"].append(rid)
            state["tombstones"].sort()
            for record in state["records"].values():
                record["supersedes"] = [item for item in record["supersedes"] if item != rid]
                if record.get("superseded_by") == rid:
                    record.pop("superseded_by")
            for event in state["events"]:
                if rid in event["ids"]:
                    # Remove action metadata potentially tied to deleted payloads.
                    event.pop("reason_sha256", None)
                event["ids"] = [item for item in event["ids"] if item != rid]
                event["published_ids"] = [item for item in event["published_ids"] if item != rid]
            result = self._commit(state, "delete", [], owner)
            result.update(deleted_id=rid, historical_payloads_removed=True)
            return result

    def status(self):
        state = self._load()
        return {"status": "ok", "schema_version": 1, "revision": state["revision"],
                "counts": {status: sum(item["status"] == status for item in state["records"].values()) for status in sorted(STATUSES)},
                "deleted_ids": len(state["tombstones"]), "reference_only": True}

    def history(self, scope, owner, project=None):
        selected_context = context(scope, owner, project)
        state = self._load()
        scoped_ids = {rid for rid, record in state["records"].items() if record_context(record) == selected_context}
        events = []
        previous = None
        for event in state["events"]:
            selected = sorted(scoped_ids.intersection(event["published_ids"]))
            affected = sorted(scoped_ids.intersection(event["ids"]))
            if event["revision"] != 0 and not affected and selected == previous:
                continue
            item = {"revision": event["revision"], "action": event["action"], "at": event["at"],
                    "ids": affected, "published_ids": selected}
            if "target_revision" in event:
                item["target_revision"] = event["target_revision"]
            events.append(item)
            previous = selected
        return {"status": "ok", "revision": state["revision"], "scope": scope, "events": events,
                "deleted_payloads_excluded": True}


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--store", type=Path, required=True)
    cli.add_argument("--lock-timeout", type=float, default=5.0)
    access.add_write_arguments(cli)
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("status")
    history = commands.add_parser("history")
    history.add_argument("--owner", required=True)
    history.add_argument("--project")
    history.add_argument("--scope", choices=["personal", "project"], required=True)
    candidate = commands.add_parser("candidate")
    candidate.add_argument("--input", type=Path, required=True)
    for name in ("retrieve", "list"):
        sub = commands.add_parser(name)
        sub.add_argument("--owner", required=True)
        sub.add_argument("--project")
        sub.add_argument("--scope", choices=["personal", "project"])
        sub.add_argument("--query")
        sub.add_argument("--limit", type=int, default=20)
        if name == "list":
            sub.add_argument("--status", choices=[*sorted(STATUSES), "all"], default="all")
    for name in ("publish", "delete", "rollback"):
        sub = commands.add_parser(name)
        sub.add_argument("--owner", required=True)
        sub.add_argument("--project")
        sub.add_argument("--reason", required=True)
        sub.add_argument("--approve", action="store_true")
        if name != "delete":
            sub.add_argument("--reviewer", required=True)
        if name == "rollback":
            sub.add_argument("--revision", required=True, type=int)
            sub.add_argument("--scope", required=True, choices=["personal", "project"])
        else:
            sub.add_argument("--id", required=True)
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        store = MemoryStore(args.store, args.lock_timeout, write_access=access.from_args(args))
        if args.command in {"init", "status"}:
            result = getattr(store, args.command)()
        elif args.command == "candidate":
            result = store.candidate(read_json(args.input))
        elif args.command == "history":
            result = store.history(args.scope, args.owner, args.project)
        elif args.command in {"retrieve", "list"}:
            result = store.retrieve(args.owner, args.project, args.query, args.limit, args.scope,
                                    status=getattr(args, "status", "published"))
        elif args.command == "publish":
            result = store.publish(args.id, args.owner, args.reviewer, args.reason, args.approve, args.project)
        elif args.command == "delete":
            result = store.delete(args.id, args.owner, args.reason, args.approve, args.project)
        else:
            result = store.rollback(args.revision, args.scope, args.owner, args.reviewer, args.reason, args.approve, args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (MemoryError, access.AccessError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
