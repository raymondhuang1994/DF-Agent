"""Explicit feedback, scoped reuse, persistence and deletion regressions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "plugins/df-agent/skills/df-agent/scripts/feedback.py"
SPEC = importlib.util.spec_from_file_location("advisor_feedback", SCRIPT)
feedback = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(feedback)


def sample(rid="feedback-001", **changes):
    record = {
        "id": rid, "scope": "project", "owner": "synthetic-person", "project": "synthetic-project",
        "workflow": "fund_flows", "task_id": "task-01", "run_id": "run-01", "outcome": "revised",
        "user_feedback": "把合计和净额分开，修改后采用。", "reason": "原稿混淆交易总额与净流入。",
        "correction": "本项目资金流报告把申购、赎回和净流入分列，净流入等于申购减赎回。",
        "observed_at": "2026-11-16T01:00:00Z",
        "artifact_refs": [{"uri": "synthetic:flow-report", "sha256": "a" * 64, "locator": "table 1"}],
        "source_refs": [{"uri": "synthetic:flow-input", "sha256": "b" * 64, "locator": "rows 2-8"}],
        "criteria": [{"name": "calculation", "status": "failed", "evidence": "Previous draft mislabeled gross flows as net flows."}],
        "revision_minutes": 4,
    }
    record.update(changes)
    return record


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="advisor-feedback-")
        self.base = Path(self.tmp.name)
        self.write_access = feedback.access.WriteAccess("synthetic-feedback-test", [self.base], ["feedback", "output", "memory"])
        self.store = feedback.Store(self.base / "state", write_access=self.write_access)
        self.scope = feedback.scope_value("project", "synthetic-person", "synthetic-project")
        self.store.init()

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_denies_writes_and_reads_do_not_create_files(self):
        self.store.record(sample(), explicit=True)
        readonly = feedback.Store(self.store.path)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.store.path.iterdir()}
        self.assertEqual(len(readonly.records(self.scope)), 1)
        self.assertEqual(readonly.summary(self.scope)["feedback_count"], 1)
        self.assertEqual(readonly.load()["revision"], 1)
        mutations = [readonly.init, lambda: readonly.record(sample("new"), explicit=True),
                     lambda: readonly.delete("feedback-001", self.scope, confirmed=True),
                     lambda: readonly.suggest("feedback-001", self.scope, "definition", self.base / "candidate.json"),
                     lambda: readonly.save(readonly.load())]
        for mutation in mutations:
            with self.assertRaises(feedback.access.AccessError):
                mutation()
        self.assertEqual({p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.store.path.iterdir()}, before)
        self.assertFalse((self.base / "candidate.json").exists())
        missing = feedback.Store(self.base / "missing")
        with self.assertRaises(feedback.access.AccessError):
            missing.init()
        with self.assertRaises(feedback.FeedbackError):
            missing.load()
        self.assertFalse(missing.path.exists())

    def test_candidate_export_requires_both_store_and_output_grants(self):
        self.store.record(sample(), explicit=True)
        before = self.store.file.read_bytes()
        denied_output = self.base / "outside-grant" / "candidate.json"
        store_only = feedback.access.WriteAccess("synthetic-feedback-test", [self.store.path], ["feedback", "output"])
        limited = feedback.Store(self.store.path, write_access=store_only)
        with self.assertRaises(feedback.access.AccessError):
            limited.suggest("feedback-001", self.scope, "definition", denied_output)
        self.assertEqual(self.store.file.read_bytes(), before)
        self.assertFalse(denied_output.parent.exists())
        output_only = feedback.access.WriteAccess("synthetic-feedback-test", [self.base], ["output"])
        limited = feedback.Store(self.store.path, write_access=output_only)
        with self.assertRaises(feedback.access.AccessError):
            limited.suggest("feedback-001", self.scope, "definition", self.base / "candidate.json")
        self.assertEqual(self.store.file.read_bytes(), before)
        self.assertFalse((self.base / "candidate.json").exists())
        self.assertFalse(self.store.lock.exists())

    def test_documents_cannot_be_used_for_feedback_or_candidate_output(self):
        documents = self.base / "documents"
        documents.mkdir()
        original = documents / "original.txt"
        original.write_text("synthetic source", encoding="utf-8")
        with self.assertRaises(feedback.access.AccessError):
            grant = feedback.access.WriteAccess("synthetic-feedback-test", [documents], ["feedback", "output"], document_roots=[documents])
            feedback.Store(documents / "feedback", write_access=grant).init()
        self.assertEqual([p.name for p in documents.iterdir()], ["original.txt"])
        self.assertEqual(original.read_text("utf-8"), "synthetic source")

    def test_silence_or_machine_check_is_not_user_acceptance(self):
        with self.assertRaises(feedback.FeedbackError):
            self.store.record(sample(), explicit=False)
        with self.assertRaises(feedback.FeedbackError):
            self.store.record(sample(outcome="unknown"), explicit=True)
        with self.assertRaises(feedback.FeedbackError):
            self.store.record(sample(user_feedback=""), explicit=True)
        self.assertEqual(self.store.records(self.scope), [])

    def test_scope_filters_person_and_project_and_does_not_allow_cross_scope_suggest(self):
        self.store.record(sample(), explicit=True)
        self.store.record(sample("feedback-002", owner="other-person"), explicit=True)
        self.store.record(sample("feedback-003", project="other-project"), explicit=True)
        personal = sample("feedback-004", scope="personal")
        del personal["project"]
        self.store.record(personal, explicit=True)
        self.assertEqual([r["id"] for r in self.store.records(self.scope)], ["feedback-001"])
        with self.assertRaises(feedback.FeedbackError):
            self.store.suggest("feedback-002", self.scope, "definition", self.base / "candidate.json")
        with self.assertRaises(feedback.FeedbackError):
            self.store.delete("feedback-003", self.scope, confirmed=True)
        self.assertFalse((self.base / "candidate.json").exists())
        with self.assertRaises(feedback.FeedbackError):
            self.store.records({})

    def test_suggestion_exports_only_selected_correction_with_provenance(self):
        self.store.record(sample(), explicit=True)
        output = self.base / "candidate.json"
        result = self.store.suggest("feedback-001", self.scope, "flow-definition", output)
        candidate = json.loads(output.read_text("utf-8"))
        self.assertFalse(result["published"])
        self.assertEqual(candidate["content"], sample()["correction"])
        self.assertEqual(candidate["feedback_ids"], ["feedback-001"])
        self.assertEqual(candidate["provenance"][0]["source"], "feedback:feedback-001")
        self.assertEqual(candidate["provenance"][1]["version"], "a" * 64)
        self.assertNotIn("user_feedback", candidate)
        self.assertNotIn("reason", candidate)
        with self.assertRaises(feedback.FeedbackError):
            self.store.suggest("feedback-001", self.scope, "flow-definition", output)

    def test_rejection_without_correction_cannot_become_memory(self):
        record = sample(outcome="rejected", selected_excerpt="不应当复用的旧写法")
        del record["correction"]
        self.store.record(record, explicit=True)
        with self.assertRaises(feedback.FeedbackError):
            self.store.suggest(record["id"], self.scope, "style", self.base / "candidate.json")

    def test_selected_accepted_excerpt_can_be_suggested_without_inventing_a_lesson(self):
        record = sample(outcome="accepted", selected_excerpt="先给净流入总数，再解释口径和覆盖。")
        del record["correction"]
        self.store.record(record, explicit=True)
        self.store.suggest(record["id"], self.scope, "report-example", self.base / "candidate.json")
        candidate = json.loads((self.base / "candidate.json").read_text("utf-8"))
        self.assertEqual(candidate["kind"], "accepted_example")
        self.assertEqual(candidate["content"], record["selected_excerpt"])

    def test_summary_denominator_is_explicit_feedback_and_missing_times_are_not_zero(self):
        self.store.record(sample(), explicit=True)
        accepted = sample("feedback-002", outcome="accepted")
        del accepted["revision_minutes"]
        self.store.record(accepted, explicit=True)
        summary = self.store.summary(self.scope)
        self.assertEqual(summary["feedback_count"], 2)
        self.assertEqual(summary["accepted_share_of_explicit_feedback"], .5)
        self.assertEqual(summary["revision_minutes"], {"observed_runs": 1, "total": 4, "mean": 4})
        empty = self.store.summary(feedback.scope_value("personal", "nobody"))
        self.assertIsNone(empty["accepted_share_of_explicit_feedback"])

    def test_timestamp_order_uses_instants_across_timezones(self):
        self.store.record(sample("early", observed_at="2026-11-16T10:00:00+09:00"), explicit=True)
        self.store.record(sample("later", observed_at="2026-11-16T03:00:00Z"), explicit=True)
        self.assertEqual([record["id"] for record in self.store.records(self.scope)], ["early", "later"])

    def test_boolean_schema_version_is_rejected_without_rewriting_store(self):
        data = json.loads(self.store.file.read_text("utf-8"))
        data["schema_version"] = True
        self.store.file.write_text(json.dumps(data), encoding="utf-8")
        before = self.store.file.read_bytes()
        with self.assertRaises(feedback.FeedbackError):
            self.store.load()
        self.assertEqual(before, self.store.file.read_bytes())

    def test_delete_erases_payload_and_returns_external_memory_followup(self):
        self.store.record(sample(), explicit=True)
        self.store.suggest("feedback-001", self.scope, "flow-definition", self.base / "candidate.json")
        with self.assertRaises(feedback.FeedbackError):
            self.store.delete("feedback-001", self.scope)
        result = self.store.delete("feedback-001", self.scope, confirmed=True)
        raw = self.store.file.read_text("utf-8")
        self.assertNotIn(sample()["correction"], raw)
        self.assertNotIn(sample()["user_feedback"], raw)
        self.assertNotIn("synthetic-person", raw)
        self.assertEqual(result["linked_memory_ids"], ["fb-feedback-001"])
        self.assertFalse(result["external_copies_erased"])
        self.assertEqual(self.store.records(self.scope), [])
        with self.assertRaises(feedback.FeedbackError):
            self.store.record(sample(), explicit=True)

    def test_busy_lock_and_invalid_input_leave_existing_records_unchanged(self):
        self.store.record(sample(), explicit=True)
        before = self.store.file.read_bytes()
        self.store.lock.write_text("synthetic-writer", encoding="ascii")
        with self.assertRaises(feedback.FeedbackError):
            self.store.record(sample("feedback-002"), explicit=True)
        self.store.lock.unlink()
        for changes in ({"observed_at": "2026-11-16T01:00:00"}, {"transcript": "not allowed"},
                        {"revision_minutes": float("nan")}, {"reason": "x" * 4001},
                        {"artifact_refs": [{"uri": "synthetic:artifact", "sha256": "short", "locator": "p1"}]}):
            with self.subTest(changes=list(changes)), self.assertRaises(feedback.FeedbackError):
                self.store.record(sample("feedback-002", **changes), explicit=True)
        self.assertEqual(self.store.file.read_bytes(), before)

    def test_state_or_candidate_cannot_be_written_inside_release(self):
        with self.assertRaises(feedback.FeedbackError):
            feedback.Store(PROJECT / "local-feedback")
        self.store.record(sample(), explicit=True)
        with self.assertRaises(feedback.FeedbackError):
            self.store.suggest("feedback-001", self.scope, "flow-definition", PROJECT / "candidate.json")

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_dangling_junction_cannot_redirect_state_or_candidate_export(self):
        target = self.base / "junction-target"
        target.mkdir()
        junction = self.base / "dangling-junction"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True, check=True)
        # Only remove this verified empty directory inside the test workspace.
        self.assertTrue(target.resolve().is_relative_to(self.base.resolve()))
        target.rmdir()
        self.assertFalse(junction.exists())
        self.assertTrue(feedback.has_link(junction))
        with self.assertRaises(feedback.FeedbackError):
            feedback.Store(junction).init()
        self.store.record(sample(), explicit=True)
        with self.assertRaises(feedback.FeedbackError):
            self.store.suggest("feedback-001", self.scope, "flow-definition", junction / "candidate.json")
        self.assertFalse(target.exists())

    def test_new_process_uses_saved_feedback(self):
        self.store.record(sample(), explicit=True)
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--store", str(self.store.path),
                                 "summary", "--scope", "project", "--owner", "synthetic-person", "--project", "synthetic-project"],
                                capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(result.stdout)["outcomes"]["revised"], 1)

    def test_export_imports_into_memory_as_invisible_candidate_until_reviewed(self):
        memory_spec = importlib.util.spec_from_file_location("feedback_memory_interop", SCRIPT.with_name("memory.py"))
        memory = importlib.util.module_from_spec(memory_spec)
        memory_spec.loader.exec_module(memory)
        self.store.record(sample(), explicit=True)
        output = self.base / "candidate.json"
        self.store.suggest("feedback-001", self.scope, "flow-definition", output)
        memory_store = memory.MemoryStore(self.base / "memory", write_access=self.write_access)
        memory_store.init()
        candidate = json.loads(output.read_text("utf-8"))
        memory_store.candidate(candidate)
        self.assertEqual(memory_store.retrieve("synthetic-person", project="synthetic-project")["records"], [])
        memory_store.publish(candidate["id"], "synthetic-person", "synthetic-reviewer", "Explicit synthetic test review", approve=True, project="synthetic-project")
        retrieved = memory_store.retrieve("synthetic-person", project="synthetic-project")["records"]
        self.assertEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0]["content"], sample()["correction"])
        self.assertEqual(retrieved[0]["feedback_ids"], ["feedback-001"])

    def test_whitespace_scope_stays_identical_across_feedback_memory_handoff(self):
        memory_spec = importlib.util.spec_from_file_location("feedback_memory_scope_interop", SCRIPT.with_name("memory.py"))
        memory = importlib.util.module_from_spec(memory_spec)
        memory_spec.loader.exec_module(memory)
        self.store.record(sample(owner=" synthetic-person ", project=" synthetic-project "), explicit=True)
        canonical = self.store.records(self.scope)
        self.assertEqual(len(canonical), 1)
        self.assertEqual(canonical[0]["owner"], "synthetic-person")
        self.assertEqual(canonical[0]["project"], "synthetic-project")
        supplied_scope = {"scope": "project", "owner": " synthetic-person ", "project": " synthetic-project "}
        self.assertEqual(self.store.records(supplied_scope), canonical)
        output = self.base / "candidate.json"
        self.store.suggest("feedback-001", supplied_scope, "flow-definition", output)
        candidate = json.loads(output.read_text("utf-8"))
        memory_store = memory.MemoryStore(self.base / "memory", write_access=self.write_access)
        memory_store.init()
        memory_store.candidate(candidate)
        memory_store.publish(candidate["id"], "synthetic-person", "reviewer", "Explicit synthetic review", approve=True, project="synthetic-project")
        retrieved = memory_store.retrieve("synthetic-person", project="synthetic-project")["records"]
        self.assertEqual(len(retrieved), len(canonical))
        self.assertEqual(retrieved[0]["owner"], canonical[0]["owner"])
        self.assertEqual(retrieved[0]["project"], canonical[0]["project"])


if __name__ == "__main__":
    unittest.main()
