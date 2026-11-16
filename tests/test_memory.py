"""Meaningful memory invariants using synthetic, isolated stores."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/df-agent/skills/df-agent/scripts/memory.py"
SPEC = importlib.util.spec_from_file_location("advisor_memory", SCRIPT)
memory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory)


def candidate(rid="memory-1", owner="synthetic-user-a", project=None, **changes):
    record = {"id": rid, "scope": "project" if project else "personal", "owner": owner,
              "key": "fund-flow-units", "content": "合成项目的资金流量使用人民币元，并保留赎回负号。",
              "kind": "definition", "provenance": [{"source": "synthetic:review", "locator": "task-01:turn-2",
              "version": "fixture-v1", "observed_at": "2026-11-16T01:00:00Z", "kind": "synthetic"}]}
    if project:
        record["project"] = project
    record.update(changes)
    return record


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="advisor-memory-")
        self.base = Path(self.temp.name)
        self.store = memory.MemoryStore(self.base / "state")
        self.store.init()

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, record):
        self.store.candidate(record)
        return self.store.publish(record["id"], record["owner"], "synthetic-reviewer", "Explicit synthetic review",
                                  approve=True, project=record.get("project"))

    def ids(self, **kwargs):
        return [record["id"] for record in self.store.retrieve("synthetic-user-a", **kwargs)["records"]]

    def test_candidates_never_enter_ordinary_retrieval(self):
        self.store.candidate(candidate())
        self.assertEqual(self.ids(), [])
        self.assertEqual(self.ids(status="candidate"), ["memory-1"])
        with self.assertRaises(memory.MemoryError):
            self.store.publish("memory-1", "synthetic-user-a", "reviewer", "reason")
        self.assertEqual(self.ids(), [])
        self.store.publish("memory-1", "synthetic-user-a", "reviewer", "Reviewed the source", approve=True)
        result = self.store.retrieve("synthetic-user-a")
        self.assertTrue(result["reference_only"])
        self.assertEqual(result["records"][0]["provenance"][0]["version"], "fixture-v1")

    def test_mutations_use_same_normalized_scope_as_retrieval(self):
        self.store.candidate(candidate("spaces", owner=" synthetic-user-a ", project=" synthetic-alpha "))
        self.store.publish("spaces", " synthetic-user-a ", "reviewer", "Explicit synthetic review",
                           approve=True, project=" synthetic-alpha ")
        self.assertEqual(self.ids(project="synthetic-alpha"), ["spaces"])
        self.store.delete("spaces", " synthetic-user-a ", "Explicit synthetic deletion",
                          approve=True, project=" synthetic-alpha ")
        self.assertEqual(self.ids(project="synthetic-alpha"), [])

    def test_scope_isolation_and_project_context(self):
        self.publish(candidate("personal-a"))
        self.publish(candidate("personal-b", owner="synthetic-user-b"))
        self.publish(candidate("project-a", project="synthetic-alpha"))
        self.publish(candidate("project-b", project="synthetic-beta"))
        self.assertEqual(self.ids(), ["personal-a"])
        self.assertCountEqual(self.ids(project="synthetic-alpha"), ["personal-a", "project-a"])
        self.assertEqual(self.ids(project="synthetic-alpha", scope="project"), ["project-a"])
        with self.assertRaises(memory.MemoryError):
            self.store.delete("personal-b", "synthetic-user-a", "wrong owner", approve=True)
        with self.assertRaises(memory.MemoryError):
            self.store.delete("project-a", "synthetic-user-a", "missing project", approve=True)

    def test_expiry_is_checked_on_every_retrieval(self):
        self.publish(candidate(expires_at="2099-01-01T00:00:00Z", kind="fact"))
        self.assertEqual(self.ids(now="2098-12-31T23:59:59Z"), ["memory-1"])
        self.assertEqual(self.ids(now="2099-01-01T00:00:00Z"), [])
        self.assertTrue(self.store.retrieve("synthetic-user-a", now="2099-01-01T00:00:00Z", status="all")["records"][0]["expired"])
        self.store.candidate(candidate("expired", key="old-fact", expires_at="2000-01-01T00:00:00Z", kind="fact"))
        with self.assertRaises(memory.MemoryError):
            self.store.publish("expired", "synthetic-user-a", "reviewer", "expired", approve=True)

    def test_conflicts_require_explicit_current_supersession(self):
        self.publish(candidate("v1"))
        self.store.candidate(candidate("conflict"))
        with self.assertRaises(memory.MemoryError):
            self.store.publish("conflict", "synthetic-user-a", "reviewer", "unresolved", approve=True)
        self.publish(candidate("v2", content="合成更正：报告以万元展示，计算层仍以元存储。", supersedes=["v1"]))
        self.assertEqual(self.ids(), ["v2"])
        self.assertEqual(self.ids(status="superseded"), ["v1"])
        with self.assertRaises(memory.MemoryError):
            self.store.candidate(candidate("v3", supersedes=["v1"]))
        with self.assertRaises(memory.MemoryError):
            self.store.candidate(candidate("v3", owner="synthetic-user-b", supersedes=["v2"]))

    def test_parallel_candidates_cannot_overwrite_newer_published_version(self):
        self.publish(candidate("v1"))
        self.store.candidate(candidate("proposal-a", supersedes=["v1"]))
        self.store.candidate(candidate("proposal-b", supersedes=["v1"]))
        self.store.publish("proposal-a", "synthetic-user-a", "reviewer", "first", approve=True)
        with self.assertRaises(memory.MemoryError):
            self.store.publish("proposal-b", "synthetic-user-a", "reviewer", "stale", approve=True)
        self.assertEqual(self.ids(), ["proposal-a"])

    def test_scoped_rollback_keeps_other_users_and_projects(self):
        revision = self.publish(candidate("old", project="synthetic-alpha"))["revision"]
        self.publish(candidate("new", project="synthetic-alpha", supersedes=["old"]))
        self.publish(candidate("other-project", project="synthetic-beta"))
        self.publish(candidate("other-owner", owner="synthetic-user-b"))
        self.store.candidate(candidate("pending", project="synthetic-alpha", key="new-definition"))
        self.store.rollback(revision, "project", "synthetic-user-a", "reviewer", "revert scoped definition", True, "synthetic-alpha")
        self.assertEqual(self.ids(project="synthetic-alpha", scope="project"), ["old"])
        self.assertEqual(self.ids(project="synthetic-beta", scope="project"), ["other-project"])
        self.assertEqual([r["id"] for r in self.store.retrieve("synthetic-user-b")["records"]], ["other-owner"])
        self.assertEqual(self.ids(project="synthetic-alpha", status="candidate"), ["pending"])
        history = self.store.history("project", "synthetic-user-a", "synthetic-alpha")
        self.assertIn(revision, [item["revision"] for item in history["events"]])
        self.assertNotIn("other-owner", json.dumps(history))
        self.assertNotIn("other-project", json.dumps(history))

    def test_deletion_erases_payload_and_cannot_be_rolled_back(self):
        secret_fixture = "SYNTHETIC-PAYLOAD-MUST-DISAPPEAR-90210"
        revision = self.publish(candidate("erase", content=secret_fixture))["revision"]
        self.store.delete("erase", "synthetic-user-a", "remove explicit memory", approve=True)
        serialized = self.store.path.read_text("utf-8")
        self.assertNotIn(secret_fixture, serialized)
        self.assertEqual(json.loads(serialized)["tombstones"], ["erase"])
        for event in json.loads(serialized)["events"]:
            self.assertNotIn("erase", event["published_ids"])
            self.assertNotIn("erase", event["ids"])
        self.store.rollback(revision, "personal", "synthetic-user-a", "reviewer", "historical view", True)
        self.assertEqual(self.ids(), [])
        with self.assertRaises(memory.MemoryError):
            self.store.candidate(candidate("erase"))
        self.assertEqual(sorted(item.name for item in self.store.directory.iterdir()), ["memory.json", "memory.lock"])

    def test_delete_successor_does_not_implicitly_reactivate_predecessor(self):
        self.publish(candidate("old"))
        self.publish(candidate("new", supersedes=["old"]))
        self.store.delete("new", "synthetic-user-a", "forget current definition", True)
        self.assertEqual(self.ids(), [])
        self.store.status()

    def test_unknown_or_malformed_input_is_rejected_without_changing_store(self):
        original = self.store.path.read_bytes()
        malformed = [candidate(scope="team"), candidate(owner=""), candidate(kind="fact"),
                     candidate(kind=[]), candidate(scope=[]), candidate(project="bad-personal-context", scope="personal"),
                     candidate(provenance=[]), candidate(expires_at="2026-11-16T00:00:00"),
                     candidate(id="../escape"), candidate(unexpected=True), candidate(supersedes=["missing"]),
                     candidate(tags=["x", "x"]), candidate(content=""), candidate(feedback_ids=[{}])]
        broken_source = candidate()
        broken_source["provenance"][0]["kind"] = []
        malformed.append(broken_source)
        for record in malformed:
            with self.subTest(record=record), self.assertRaises(memory.MemoryError):
                self.store.candidate(record)
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_corrupt_store_is_never_silently_reinitialized(self):
        self.store.path.write_text('{"schema_version": 1}', encoding="utf-8")
        with self.assertRaises(memory.MemoryError):
            self.store.status()
        with self.assertRaises(memory.MemoryError):
            self.store.init()
        self.assertEqual(self.store.path.read_text("utf-8"), '{"schema_version": 1}')

    def test_missing_normalized_fields_in_manual_store_fail_cleanly(self):
        self.store.candidate(candidate())
        state = json.loads(self.store.path.read_text("utf-8"))
        del state["records"]["memory-1"]["supersedes"]
        self.store.path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(memory.MemoryError):
            self.store.delete("memory-1", "synthetic-user-a", "malformed record", True)

    def test_atomic_failure_preserves_previous_snapshot(self):
        original = self.store.path.read_bytes()
        with patch.object(memory.os, "replace", side_effect=OSError("Synthetic replacement failure")):
            with self.assertRaises((memory.MemoryError, OSError)):
                self.store.candidate(candidate())
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(list(self.store.directory.glob("*.tmp")), [])
        self.store.candidate(candidate())

    def test_concurrent_processes_do_not_lose_updates(self):
        processes = []
        for number in range(6):
            source = self.base / f"candidate-{number}.json"
            source.write_text(json.dumps(candidate(f"process-{number}", key=f"definition-{number}")), encoding="utf-8")
            processes.append(subprocess.Popen([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--store", str(self.store.directory),
                                               "candidate", "--input", str(source)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"))
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        status = self.store.status()
        self.assertEqual(status["revision"], 6)
        self.assertEqual(status["counts"]["candidate"], 6)

    def test_lock_contention_is_bounded(self):
        with self.store._locked():
            process = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--store", str(self.store.directory),
                                      "--lock-timeout", "0.1", "status"], capture_output=True, text=True, encoding="utf-8", timeout=5)
            self.assertEqual(process.returncode, 1)
            self.assertIn("busy", json.loads(process.stdout)["error"])
        self.assertEqual(self.store.status()["revision"], 0)

    def test_rejects_storage_inside_plugin_or_repository(self):
        for path in [ROOT / "state", SCRIPT.parent / "state"]:
            with self.assertRaises(memory.MemoryError):
                memory.MemoryStore(path)
        with self.assertRaises(memory.MemoryError):
            memory.MemoryStore("relative/state")

    def test_cli_round_trip_unicode_and_explicit_review(self):
        source = self.base / "候选 [一].json"
        source.write_text(json.dumps(candidate(), ensure_ascii=False), encoding="utf-8")
        command = [sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--store", str(self.store.directory)]
        created = subprocess.run(command + ["candidate", "--input", str(source)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        published = subprocess.run(command + ["publish", "--id", "memory-1", "--owner", "synthetic-user-a", "--reviewer", "reviewer",
                                               "--reason", "确认合成示例", "--approve"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
        retrieved = subprocess.run(command + ["retrieve", "--owner", "synthetic-user-a", "--query", "资金流量"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(retrieved.returncode, 0, retrieved.stdout + retrieved.stderr)
        self.assertEqual(json.loads(retrieved.stdout)["records"][0]["id"], "memory-1")


if __name__ == "__main__":
    unittest.main()
