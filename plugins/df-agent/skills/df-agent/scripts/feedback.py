#!/usr/bin/env python3
"""Scoped explicit feedback records and reviewed-memory candidate suggestions.

Standard library only. Never reads referenced artifacts, contacts a service, or
publishes memories. Scope labels filter retrieval; they are not OS access control.
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
import tempfile

if "df_agent_write_access" not in sys.modules:
    _ACCESS_SPEC = importlib.util.spec_from_file_location("df_agent_write_access", Path(__file__).with_name("access.py"))
    _ACCESS_MODULE = importlib.util.module_from_spec(_ACCESS_SPEC)
    sys.modules["df_agent_write_access"] = _ACCESS_MODULE
    _ACCESS_SPEC.loader.exec_module(_ACCESS_MODULE)
access = sys.modules["df_agent_write_access"]

SCHEMA = 1
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,49}\Z")
HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
WORKFLOWS = {"product_comments", "fund_flows"}
OUTCOMES = {"accepted", "revised", "rejected"}
CHECKS = {"passed", "failed", "not_checked"}
MAX_INPUT_BYTES = 128 * 1024
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = Path(__file__).resolve().parents[5]


class FeedbackError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def text_value(value, label, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise FeedbackError(f"{label} must be nonempty text, at most {limit} characters")
    return value


def timestamp(value, label):
    text_value(value, label, 80)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise FeedbackError(f"{label} must be an ISO8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FeedbackError(f"{label} requires a timezone")
    return parsed.astimezone(timezone.utc)


def exact_keys(value, required, optional=(), label="object"):
    if not isinstance(value, dict):
        raise FeedbackError(f"{label} must be an object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        raise FeedbackError(f"Invalid {label} fields: missing={sorted(missing)}, extra={sorted(extra)}")


def scope_value(scope, owner, project=None):
    if scope not in {"personal", "project"}:
        raise FeedbackError("scope must be personal or project")
    owner = text_value(owner, "owner", 128).strip()
    if scope == "project":
        project = text_value(project, "project", 160).strip()
    elif project is not None:
        raise FeedbackError("Personal feedback must not have a project")
    result = {"scope": scope, "owner": owner}
    if project is not None:
        result["project"] = project
    return result


def validate_scope(value):
    exact_keys(value, {"scope", "owner"}, {"project"}, "query scope")
    return scope_value(value["scope"], value["owner"], value.get("project"))


def references(value, label, allow_empty=False):
    if not isinstance(value, list) or len(value) > 40 or (not value and not allow_empty):
        raise FeedbackError(f"{label} must contain {'0' if allow_empty else '1'} to 40 references")
    for entry in value:
        exact_keys(entry, {"uri", "sha256", "locator"}, label=label)
        text_value(entry["uri"], f"{label}.uri", 2000)
        text_value(entry["locator"], f"{label}.locator", 1000)
        if not isinstance(entry["sha256"], str) or not HASH.fullmatch(entry["sha256"]):
            raise FeedbackError(f"{label}.sha256 must be a full SHA-256 digest")


def validate_record(record):
    required = {"id", "scope", "owner", "workflow", "task_id", "run_id", "outcome",
                "user_feedback", "reason", "observed_at", "artifact_refs", "source_refs", "criteria"}
    optional = {"project", "correction", "selected_excerpt", "revision_minutes"}
    exact_keys(record, required, optional, "feedback record")
    if not isinstance(record["id"], str) or not ID.fullmatch(record["id"]):
        raise FeedbackError("id must be 1 to 50 ASCII letters, digits, periods, underscores or hyphens")
    normalized_scope = scope_value(record["scope"], record["owner"], record.get("project"))
    if record["workflow"] not in WORKFLOWS:
        raise FeedbackError("workflow must be product_comments or fund_flows")
    if record["outcome"] not in OUTCOMES:
        raise FeedbackError("outcome must be accepted, revised or rejected; silence is not feedback")
    for name in ("task_id", "run_id"):
        text_value(record[name], name, 160)
    for name in ("user_feedback", "reason"):
        text_value(record[name], name)
    for name in ("correction", "selected_excerpt"):
        if name in record:
            text_value(record[name], name)
    timestamp(record["observed_at"], "observed_at")
    references(record["artifact_refs"], "artifact_refs")
    references(record["source_refs"], "source_refs", allow_empty=True)
    criteria = record["criteria"]
    if not isinstance(criteria, list) or len(criteria) > 20:
        raise FeedbackError("criteria must be a list of at most 20 checks")
    names = set()
    for entry in criteria:
        exact_keys(entry, {"name", "status", "evidence"}, label="criterion")
        text_value(entry["name"], "criterion.name", 100)
        text_value(entry["evidence"], "criterion.evidence", 2000)
        if entry["name"] in names or entry["status"] not in CHECKS:
            raise FeedbackError("Criteria must have unique names and explicit check statuses")
        names.add(entry["name"])
    if "revision_minutes" in record:
        minutes = record["revision_minutes"]
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 0 <= minutes <= 100000:
            raise FeedbackError("revision_minutes must be a finite nonnegative number")
    normalized_record = deepcopy(record)
    normalized_record.update(normalized_scope)
    if normalized_record["scope"] == "personal":
        normalized_record.pop("project", None)
    return normalized_record


def has_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def external_path(raw):
    path = Path(raw).absolute()
    for ancestor in (path, *path.parents):
        if has_link(ancestor):
            raise FeedbackError("Feedback paths must not traverse links or reparse points")
    resolved = path.resolve()
    if resolved.is_relative_to(PLUGIN_ROOT):
        raise FeedbackError("Feedback state and exports must be outside the plugin")
    if (SOURCE_ROOT / ".agents/plugins/marketplace.json").is_file() and resolved.is_relative_to(SOURCE_ROOT):
        raise FeedbackError("Feedback state and exports must be outside the release repository")
    return resolved


def read_json(path):
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise FeedbackError("Feedback input is too large; supply selected feedback, not a transcript")
    try:
        return json.loads(path.read_text("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FeedbackError("Invalid UTF-8 JSON") from error


def atomic_json(path, value, *, write_access=None):
    access.require_write(write_access, path, "feedback")
    external_path(path)
    fd, temporary = tempfile.mkstemp(prefix=".feedback-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, path, *, write_access=None):
        self.path = external_path(path)
        self.file = self.path / "feedback.json"
        self.lock = self.path / ".feedback.lock"
        self.write_access = write_access

    @contextmanager
    def writing(self, initialize=False):
        access.require_write(self.write_access, self.path, "feedback")
        access.require_write(self.write_access, self.file, "feedback")
        external_path(self.path)
        if initialize:
            self.path.mkdir(parents=True, exist_ok=True)
        if not self.path.is_dir():
            raise FeedbackError("Feedback store is not initialized; run init first")
        external_path(self.lock)
        try:
            descriptor = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise FeedbackError("Feedback store has an active or stale lock. Retry after an active writer finishes. After a crash, inspect the lock PID and remove only the confirmed stale lock; never remove an active lock") from error
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(str(os.getpid()))
            yield
        finally:
            self.lock.unlink()

    def load(self):
        external_path(self.file)
        if not self.file.is_file():
            raise FeedbackError("Feedback store is not initialized; run init first")
        try:
            data = json.loads(self.file.read_text("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise FeedbackError("Feedback store is malformed; original file preserved") from error
        exact_keys(data, {"schema_version", "revision", "records", "deleted_ids"}, label="store")
        if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA or not isinstance(data["records"], dict) or not isinstance(data["deleted_ids"], list):
            raise FeedbackError("Unsupported feedback store")
        if isinstance(data["revision"], bool) or not isinstance(data["revision"], int) or data["revision"] < 0:
            raise FeedbackError("Invalid store revision")
        for rid, record in data["records"].items():
            exact_keys(record, {"record", "recorded_at", "suggested_memory_ids"}, label="stored record")
            record["record"] = validate_record(record["record"])
            timestamp(record["recorded_at"], "recorded_at")
            if rid != record["record"]["id"] or rid in data["deleted_ids"]:
                raise FeedbackError("Invalid stored feedback identity")
            if not isinstance(record["suggested_memory_ids"], list) or any(mid != "fb-" + rid for mid in record["suggested_memory_ids"]):
                raise FeedbackError("Invalid linked memory identifiers")
        if any(not isinstance(rid, str) or not ID.fullmatch(rid) for rid in data["deleted_ids"]):
            raise FeedbackError("Invalid deleted identifiers")
        return data

    def init(self):
        with self.writing(initialize=True):
            if self.file.exists():
                data = self.load()
                return {"status": "already_initialized", "revision": data["revision"]}
            atomic_json(self.file, {"schema_version": SCHEMA, "revision": 0, "records": {}, "deleted_ids": []}, write_access=self.write_access)
        return {"status": "initialized", "revision": 0}

    def save(self, data):
        access.require_write(self.write_access, self.file, "feedback")
        data["revision"] += 1
        atomic_json(self.file, data, write_access=self.write_access)

    def record(self, value, explicit=False):
        if explicit is not True:
            raise FeedbackError("Recording requires explicit user feedback; pass --explicit-feedback only when observed")
        record = validate_record(value)
        with self.writing():
            data = self.load()
            rid = record["id"]
            if rid in data["records"] or rid in data["deleted_ids"]:
                raise FeedbackError("Feedback ID is already used; use a new run-specific ID")
            data["records"][rid] = {"record": record, "recorded_at": now(), "suggested_memory_ids": []}
            self.save(data)
        return {"status": "recorded", "id": rid, "revision": data["revision"]}

    @staticmethod
    def matches(record, scope):
        return all(record.get(key) == value for key, value in scope.items()) and record.get("project") == scope.get("project")

    def selected(self, data, rid, scope):
        wrapped = data["records"].get(rid)
        if wrapped is None or not self.matches(wrapped["record"], scope):
            raise FeedbackError("Feedback ID is absent from the requested scope")
        return wrapped

    def records(self, scope, workflow=None):
        scope = validate_scope(scope)
        if workflow is not None and workflow not in WORKFLOWS:
            raise FeedbackError("Unknown workflow")
        data = self.load()
        records = [deepcopy(value["record"]) for value in data["records"].values()
                   if self.matches(value["record"], scope) and (workflow is None or value["record"]["workflow"] == workflow)]
        return sorted(records, key=lambda item: (timestamp(item["observed_at"], "observed_at"), item["id"]))

    def summary(self, scope, workflow=None):
        records = self.records(scope, workflow)
        counts = {key: sum(record["outcome"] == key for record in records) for key in sorted(OUTCOMES)}
        minutes = [record["revision_minutes"] for record in records if "revision_minutes" in record]
        return {"scope": scope, "workflow": workflow, "feedback_count": len(records), "outcomes": counts,
                "accepted_share_of_explicit_feedback": counts["accepted"] / len(records) if records else None,
                "revision_minutes": {"observed_runs": len(minutes), "total": sum(minutes),
                                     "mean": sum(minutes) / len(minutes) if minutes else None},
                "interpretation": "Only selected explicit feedback is counted; this is not an all-task adoption rate or a causal quality improvement estimate."}

    def suggest(self, rid, scope, key, output):
        scope = validate_scope(scope)
        text_value(key, "memory key", 160)
        output = external_path(output)
        # Both grants must pass before locking or updating linked-memory metadata.
        access.require_write(self.write_access, self.path, "feedback")
        access.require_write(self.write_access, output, "output")
        if output.exists():
            raise FeedbackError("Refusing to overwrite an existing candidate export")
        with self.writing():
            data = self.load()
            wrapped = self.selected(data, rid, scope)
            record = wrapped["record"]
            content = record.get("correction") or (record.get("selected_excerpt") if record["outcome"] == "accepted" else None)
            if not content:
                raise FeedbackError("Memory suggestion needs an explicit correction or a selected accepted excerpt")
            mid = "fb-" + rid
            version = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            provenance = [{"source": "feedback:" + rid, "locator": "task:" + record["task_id"] + "/run:" + record["run_id"],
                           "version": version, "observed_at": record["observed_at"], "kind": "user_feedback"}]
            for ref in (record["artifact_refs"] + record["source_refs"])[:19]:
                provenance.append({"source": ref["uri"], "locator": ref["locator"], "version": ref["sha256"],
                                   "observed_at": record["observed_at"], "kind": "artifact"})
            candidate = {"id": mid, **scope, "key": key, "content": content, "kind": "lesson" if record.get("correction") else "accepted_example",
                         "provenance": provenance, "feedback_ids": [rid], "tags": [record["workflow"]]}
            # Register the link before creating the external export. A crash can
            # leave a harmless extra link, but never an untracked exported memory.
            if mid not in wrapped["suggested_memory_ids"]:
                wrapped["suggested_memory_ids"].append(mid)
                self.save(data)
            output.parent.mkdir(parents=True, exist_ok=True)
            external_path(output)
            access.require_write(self.write_access, output, "output")
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(candidate, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        return {"status": "candidate_exported", "memory_candidate_id": mid, "output": str(output),
                "published": False, "next": "Review scope, staleness and conflicts; import as a memory candidate. Explicit review is still required to publish."}

    def delete(self, rid, scope, confirmed=False):
        scope = validate_scope(scope)
        if confirmed is not True:
            raise FeedbackError("Deletion requires --confirm and the exact requested scope")
        with self.writing():
            data = self.load()
            wrapped = self.selected(data, rid, scope)
            linked = list(wrapped["suggested_memory_ids"])
            del data["records"][rid]
            data["deleted_ids"].append(rid)
            self.save(data)
        return {"status": "deleted", "id": rid, "linked_memory_ids": linked,
                "external_copies_erased": False,
                "next": "Delete any linked memory IDs and candidate export files separately. Source artifacts and external backups are unchanged."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    access.add_write_arguments(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    record = sub.add_parser("record")
    record.add_argument("--input", type=Path, required=True)
    record.add_argument("--explicit-feedback", action="store_true")
    for command in ("list", "summary", "suggest", "delete"):
        action = sub.add_parser(command)
        action.add_argument("--scope", choices=("personal", "project"), required=True)
        action.add_argument("--owner", required=True)
        action.add_argument("--project")
        if command in {"list", "summary"}:
            action.add_argument("--workflow", choices=sorted(WORKFLOWS))
        else:
            action.add_argument("--id", required=True)
        if command == "suggest":
            action.add_argument("--key", required=True)
            action.add_argument("--output", type=Path, required=True)
        if command == "delete":
            action.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    try:
        store = Store(args.store, write_access=access.from_args(args))
        if args.command == "init":
            result = store.init()
        elif args.command == "status":
            data = store.load()
            result = {"status": "initialized", "schema_version": SCHEMA, "revision": data["revision"], "access_control": "filesystem_only"}
        elif args.command == "record":
            result = store.record(read_json(args.input), args.explicit_feedback)
        else:
            scope = scope_value(args.scope, args.owner, args.project)
            if args.command == "list":
                result = {"records": store.records(scope, args.workflow)}
            elif args.command == "summary":
                result = store.summary(scope, args.workflow)
            elif args.command == "suggest":
                result = store.suggest(args.id, scope, args.key, args.output)
            else:
                result = store.delete(args.id, scope, args.confirm)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (FeedbackError, access.AccessError, OSError, TypeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
