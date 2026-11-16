"""Meaningful memory invariants using synthetic, isolated stores."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
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
        self.write_access = memory.access.WriteAccess("synthetic-memory-test", [self.base], ["memory"])
        self.store = memory.MemoryStore(self.base / "state", write_access=self.write_access)
        self.store.init()

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, record):
        self.store.candidate(record)
        return self.store.publish(record["id"], record["owner"], "synthetic-reviewer", "Explicit synthetic review",
                                  approve=True, project=record.get("project"))

    def ids(self, **kwargs):
        return [record["id"] for record in self.store.retrieve("synthetic-user-a", **kwargs)["records"]]

    def write_flags(self):
        return ["--task-id", "synthetic-memory-test", "--write-root", str(self.base), "--allow-operation", "memory"]

    def test_default_denies_all_mutations_without_creating_files(self):
        self.store.candidate(candidate("pending"))
        readonly = memory.MemoryStore(self.store.directory)
        before = {p.name: p.read_bytes() for p in self.store.directory.iterdir()}
        mutations = [readonly.init, lambda: readonly.candidate(candidate("new")),
                     lambda: readonly.publish("pending", "synthetic-user-a", "reviewer", "reviewed", True),
                     lambda: readonly.delete("pending", "synthetic-user-a", "forget", True),
                     lambda: readonly.rollback(0, "personal", "synthetic-user-a", "reviewer", "revert", True)]
        for mutation in mutations:
            with self.assertRaises(memory.access.AccessError):
                mutation()
        self.assertEqual({p.name: p.read_bytes() for p in self.store.directory.iterdir()}, before)
        missing = self.base / "missing"
        with self.assertRaises(memory.access.AccessError):
            memory.MemoryStore(missing).init()
        self.assertFalse(missing.exists())

    def test_readonly_queries_leave_missing_lock_and_snapshot_unchanged(self):
        self.publish(candidate())
        (self.store.directory / "memory.lock").unlink()
        readonly = memory.MemoryStore(self.store.directory)
        before = self.store.path.read_bytes(), self.store.path.stat().st_mtime_ns
        self.assertEqual(readonly.status()["revision"], 2)
        self.assertEqual(readonly.retrieve("synthetic-user-a")["records"][0]["id"], "memory-1")
        self.assertEqual(readonly.history("personal", "synthetic-user-a")["revision"], 2)
        self.assertEqual((self.store.path.read_bytes(), self.store.path.stat().st_mtime_ns), before)
        self.assertEqual([p.name for p in self.store.directory.iterdir()], ["memory.json"])
        missing = memory.MemoryStore(self.base / "missing")
        for query in (missing.status, lambda: missing.retrieve("synthetic-user-a"),
                      lambda: missing.history("personal", "synthetic-user-a")):
            with self.assertRaises(memory.MemoryError):
                query()
        self.assertFalse(missing.directory.exists())

    def test_cli_without_bytecode_flag_is_readonly_and_default_write_is_denied(self):
        # A fresh installed copy has no preexisting __pycache__ to mask writes.
        scripts = self.base / "plugin" / "skills" / "df-agent" / "scripts"
        scripts.mkdir(parents=True)
        for source in (SCRIPT, SCRIPT.with_name("access.py")):
            (scripts / source.name).write_bytes(source.read_bytes())
        command = [sys.executable, "-X", "utf8", str(scripts / "memory.py"), "--store", str(self.store.directory)]
        queried = subprocess.run(command + ["status"], capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(queried.returncode, 0, queried.stdout + queried.stderr)
        self.assertEqual(json.loads(queried.stdout)["revision"], 0)
        missing = self.base / "cli-missing"
        denied = subprocess.run([sys.executable, str(scripts / "memory.py"), "--store", str(missing), "init"],
                                capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(denied.returncode, 1, denied.stdout + denied.stderr)
        self.assertIn("Read-only", json.loads(denied.stdout)["error"])
        self.assertFalse(missing.exists())
        self.assertEqual(sorted(p.name for p in scripts.iterdir()), ["access.py", "memory.py"])

    def test_store_outside_grant_or_in_documents_cannot_be_initialized(self):
        allowed = self.base / "allowed"
        outside = self.base / "outside"
        grant = memory.access.WriteAccess("synthetic-memory-test", [allowed], ["memory"])
        with self.assertRaises(memory.access.AccessError):
            memory.MemoryStore(outside, write_access=grant).init()
        self.assertFalse(outside.exists())
        documents = self.base / "documents"
        documents.mkdir()
        original = documents / "original.txt"
        original.write_text("synthetic source stays unchanged", encoding="utf-8")
        before = original.read_bytes()
        with self.assertRaises(memory.access.AccessError):
            grant = memory.access.WriteAccess("synthetic-memory-test", [documents], ["memory"], document_roots=[documents])
            memory.MemoryStore(documents / "memory", write_access=grant).init()
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual([p.name for p in documents.iterdir()], ["original.txt"])

    def test_hardlinked_lock_cannot_write_into_readonly_source(self):
        documents = self.base / "readonly-source"
        documents.mkdir()
        source = documents / "empty.txt"
        source.write_bytes(b"")
        lock_path = self.store.directory / "memory.lock"
        lock_path.unlink()
        os.link(source, lock_path)
        grant = memory.access.WriteAccess("synthetic-memory-test", [self.store.directory], ["memory"],
                                          document_roots=[documents])
        store = memory.MemoryStore(self.store.directory, write_access=grant)
        before = self.store.path.read_bytes()
        with self.assertRaises(memory.access.AccessError):
            store.candidate(candidate())
        self.assertEqual(source.read_bytes(), b"")
        self.assertEqual(lock_path.read_bytes(), b"")
        self.assertEqual(self.store.path.read_bytes(), before)

    @unittest.skipUnless(os.name == "nt", "Windows sharing regression")
    def test_held_reader_keeps_complete_snapshot_while_process_writer_retries(self):
        source = self.base / "concurrent-candidate.json"
        source.write_text(json.dumps(candidate()), encoding="utf-8")
        worker = textwrap.dedent('''
            import importlib.util, json, sys
            from pathlib import Path
            spec = importlib.util.spec_from_file_location("reader_writer_test", sys.argv[1])
            memory = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(memory)
            replace = memory.os.replace
            def observed_replace(source, destination):
                try:
                    return replace(source, destination)
                except OSError as error:
                    print(json.dumps({"blocked": getattr(error, "winerror", None)}), flush=True)
                    raise
            memory.os.replace = observed_replace
            directory = Path(sys.argv[2])
            grant = memory.access.WriteAccess("synthetic-concurrency", [directory], ["memory"])
            store = memory.MemoryStore(directory, write_access=grant)
            print(json.dumps(store.candidate(memory.read_json(Path(sys.argv[3])))), flush=True)
        ''')
        # The first real sharing failure signals us to finish reading and close
        # the old handle; the separate writer process must then commit once.
        with self.store.path.open("rb") as reader:
            process = subprocess.Popen([sys.executable, "-X", "utf8", "-B", "-c", worker,
                                        str(SCRIPT), str(self.store.directory), str(source)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            first = process.stdout.readline()
            self.assertIn(json.loads(first)["blocked"], {5, 32, 33})
            old = memory.validate_state(json.load(reader))
            self.assertEqual(old["revision"], 0)
            self.assertEqual(old["records"], {})
            self.assertEqual(len(old["events"]), 1)
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, first + stdout + stderr)
        self.assertEqual(json.loads(stdout.splitlines()[-1])["revision"], 1)
        new = memory.validate_state(memory.read_json(self.store.path))
        self.assertEqual(new["revision"], 1)
        self.assertEqual(set(new["records"]), {"memory-1"})
        self.assertEqual(len(new["events"]), 2)
        self.assertEqual(sorted(p.name for p in self.store.directory.iterdir()), ["memory.json", "memory.lock"])

    @unittest.skipUnless(os.name == "nt", "Windows sharing regression")
    def test_reader_sharing_timeout_preserves_snapshot_and_cleans_temporary_file(self):
        store = memory.MemoryStore(self.store.directory, lock_timeout=0.1, write_access=self.write_access)
        before = self.store.path.read_bytes()
        started = time.monotonic()
        with self.store.path.open("rb") as reader:
            with self.assertRaises(memory.MemoryError):
                store.candidate(candidate())
            self.assertEqual(reader.read(), before)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.store.directory.iterdir()), ["memory.json", "memory.lock"])

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
                                               *self.write_flags(), "candidate", "--input", str(source)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"))
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        status = self.store.status()
        self.assertEqual(status["revision"], 6)
        self.assertEqual(status["counts"]["candidate"], 6)

    def test_lock_contention_is_bounded(self):
        source = self.base / "locked-candidate.json"
        source.write_text(json.dumps(candidate()), encoding="utf-8")
        with self.store._locked():
            process = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--store", str(self.store.directory),
                                      *self.write_flags(), "--lock-timeout", "0.1", "candidate", "--input", str(source)],
                                     capture_output=True, text=True, encoding="utf-8", timeout=5)
            self.assertEqual(process.returncode, 1)
            self.assertIn("busy", json.loads(process.stdout)["error"])
            reader = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--store", str(self.store.directory),
                                     "status"], capture_output=True, text=True, encoding="utf-8", timeout=5)
            self.assertEqual(reader.returncode, 0, reader.stdout + reader.stderr)
            self.assertEqual(json.loads(reader.stdout)["revision"], 0)
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
        command = [sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--store", str(self.store.directory), *self.write_flags()]
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
