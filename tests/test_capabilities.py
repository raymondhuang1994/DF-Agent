"""Behavioral checks for bounded discovery, evidence freshness and readiness."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "plugins/team-advisor-entry/skills/team-advisor/scripts/doctor.py"
SPEC = importlib.util.spec_from_file_location("advisor_doctor", SCRIPT)
doctor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doctor)


def fake_probe(pandas="2.3.3", matplotlib=None):
    return {"python": [3, 12, 14], "implementation": "CPython", "packages": {
        "pandas": pandas, "numpy": "2.3.5", "matplotlib": matplotlib, "tzdata": "2026.6",
        "scipy": None, "scikit-learn": None, "python-docx": "1.2.0", "openpyxl": "3.1.5"}}


class CapabilitiesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="advisor-tests-")
        self.base = Path(self.tmp.name)
        self.root = self.base / "批准 技能 [范围]"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def make_skill(self, skill_id, directory=None):
        folder = self.root / (directory or skill_id)
        folder.mkdir()
        (folder / "SKILL.md").write_text(f"---\nname: {skill_id}\ndescription: 合成测试说明。\n---\n# Fixture\n", encoding="utf-8")
        required = set()
        for profile, definition in doctor.PROFILES.items():
            if profile.rsplit(".", 1)[0] == skill_id:
                required.update(definition["resources"])
        if skill_id == "data-lab":
            required.update(doctor.DATALAB_CORE)
        for relative in required:
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("raise RuntimeError('Do not execute fixture scripts')\n" if target.suffix == ".py" else "# 合成公共说明\n", encoding="utf-8")
        return folder

    def scan(self, **kwargs):
        return doctor.scan([self.root], session_id="test-session-01", **kwargs)

    def item(self, report, profile):
        return next(item for item in report["skills"] if item["task_profile"] == profile)

    def evidence(self, report, profile, **checks):
        item = self.item(report, profile)
        return {"environment": copy.deepcopy(report["environment"]),
                "observation_context": copy.deepcopy(report["observation_context"]),
                "observed_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(), "skills": [{
                    "source_ref": item["source_ref"], "task_profile": profile,
                    "source_fingerprint": copy.deepcopy(item["source_fingerprint"]),
                    "checks": {key: doctor.check(value, "Synthetic observation TEST-01") for key, value in checks.items()}}]}

    def test_readable_skill_not_ready_without_host_and_smoke(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        item = self.item(report, "etf-comment-drafts-v2.draft")
        self.assertEqual(item["checks"]["filesystem"]["status"], "passed")
        self.assertEqual(item["checks"]["host_discovery"]["status"], "unknown")
        self.assertIsNone(item["execution_ready"])
        self.assertTrue(doctor.validate(report))

    def test_utf8_literal_paths_and_new_output(self):
        self.make_skill("etf-comment-drafts-v2", "评论 副本 [甲]")
        report = self.scan()
        out = self.base / "结果 [新]" / "能力 清单.json"
        doctor.write_json(out, report, [self.root])
        recovered = doctor.read_json(out)
        self.assertEqual(self.item(recovered, "etf-comment-drafts-v2.draft")["source_ref"], "ROOT_1/评论 副本 [甲]/SKILL.md")
        self.assertNotIn(str(self.root), out.read_text(encoding="utf-8"))
        with self.assertRaises(doctor.CheckError):
            doctor.write_json(out, report, [self.root])

    def test_missing_resource_is_a_real_blocker(self):
        folder = self.make_skill("etf-comment-drafts-v2")
        (folder / "references/contrasts.md").unlink()
        item = self.item(self.scan(), "etf-comment-drafts-v2.draft")
        self.assertEqual(item["checks"]["resource_access"]["status"], "failed")
        self.assertIs(item["execution_ready"], False)

    def test_same_name_keeps_sources_separate_until_bound(self):
        self.make_skill("etf-comment-drafts-v2", "版本甲")
        self.make_skill("etf-comment-drafts-v2", "版本乙")
        report = self.scan()
        self.assertEqual(report["source_selection"]["etf-comment-drafts-v2"]["status"], "ambiguous")
        entries = [item for item in report["skills"] if item["skill_id"] == "etf-comment-drafts-v2"]
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(item["execution_ready"] is None for item in entries))
        binding = {"preferred_sources": {"etf-comment-drafts-v2": "ROOT_1/版本乙/SKILL.md"}}
        report = self.scan(bindings=binding)
        self.assertEqual(report["source_selection"]["etf-comment-drafts-v2"]["source_ref"], "ROOT_1/版本乙/SKILL.md")

    def test_repeated_root_is_not_a_duplicate_installation(self):
        self.make_skill("etf-comment-drafts-v2")
        report = doctor.scan([self.root, self.root], session_id="test")
        self.assertEqual(len([item for item in report["skills"] if item["skill_id"] == "etf-comment-drafts-v2"]), 1)

    def test_public_only_does_not_read_env_or_private_library(self):
        folder = self.make_skill("etf-comment-drafts-v2")
        (folder / "private").mkdir()
        secret = folder / "private/examples.json"
        secret.write_text("not approved", encoding="utf-8")
        (folder / ".env").write_text("SECRET=not approved", encoding="utf-8")
        paths = []
        original = doctor.read_bytes
        def observed(path):
            paths.append(Path(path))
            return original(path)
        with patch.object(doctor, "read_bytes", side_effect=observed):
            self.scan()
        self.assertNotIn(secret, paths)
        self.assertNotIn(folder / ".env", paths)

    def test_cannot_write_inside_sources_or_replace_input(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        with self.assertRaises(doctor.CheckError):
            doctor.write_json(self.root / "new-report.json", report, [self.root])
        protected = self.base / "evidence.json"
        with self.assertRaises(doctor.CheckError):
            doctor.write_json(protected, report, [self.root], [protected])

    def test_symlink_does_not_expand_read_or_write_scope(self):
        outside = self.base / "outside"
        outside.mkdir()
        link = self.root / "etf-comment-drafts-v2"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Host does not allow unprivileged symlink creation.")
        item = self.item(self.scan(), "etf-comment-drafts-v2.draft")
        self.assertEqual(item["checks"]["filesystem"]["status"], "failed")
        out_link = self.base / "out-link"
        out_link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(doctor.CheckError):
            doctor.write_json(out_link / "report.json", self.scan(), [self.root])
        self.assertFalse((outside / "report.json").exists())

    def test_scan_limit_is_visible_as_incomplete_coverage(self):
        with patch.object(doctor, "MAX_CHILDREN", 2):
            for name in ("a", "b", "c"):
                (self.root / name).mkdir()
            report = self.scan()
        self.assertTrue(report["coverage_limitations"])
        self.assertEqual(self.item(report, "data-lab.sum_table")["checks"]["filesystem"]["status"], "unknown")

    def test_windows_junction_cannot_expand_source_or_output(self):
        powershell = shutil.which("pwsh")
        if os.name != "nt" or not powershell:
            self.skipTest("Windows PowerShell is not available.")
        outside = self.base / "outside-junction"
        outside.mkdir()
        junction = self.root / "etf-comment-drafts-v2"
        helper = self.base / "create-junction.ps1"
        helper.write_text("param([string]$LinkPath,[string]$TargetPath)\n$ErrorActionPreference = 'Stop'\nNew-Item -ItemType Junction -Path $LinkPath -Target $TargetPath | Out-Null\n", encoding="utf-8")
        run = subprocess.run([powershell, "-NoProfile", "-File", str(helper), "-LinkPath", str(junction), "-TargetPath", str(outside)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        try:
            item = self.item(self.scan(), "etf-comment-drafts-v2.draft")
            self.assertEqual(item["checks"]["filesystem"]["status"], "failed")
            with self.assertRaises(doctor.CheckError):
                doctor.write_json(junction / "report.json", self.scan(), [self.root])
            self.assertFalse((outside / "report.json").exists())
        finally:
            # Remove only the junction itself, never recurse through the target.
            os.rmdir(junction)

    def test_invalid_metadata_and_missing_core_script_are_reported(self):
        folder = self.make_skill("data-lab")
        core = folder / "scripts/datalab/cli.py"
        core.unlink()
        item = self.item(self.scan(), "data-lab.sum_table")
        self.assertEqual(item["checks"]["resource_access"]["status"], "failed")
        (folder / "SKILL.md").write_text("# No frontmatter", encoding="utf-8")
        item = self.item(self.scan(), "data-lab.sum_table")
        self.assertEqual(item["checks"]["filesystem"]["status"], "failed")

    def test_conflicting_duplicate_observations_are_rejected(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        evidence = self.evidence(report, "etf-comment-drafts-v2.draft", smoke_test="passed")
        evidence["skills"].append(copy.deepcopy(evidence["skills"][0]))
        evidence["skills"][1]["checks"]["smoke_test"]["status"] = "failed"
        with self.assertRaises(doctor.CheckError):
            doctor.merge(report, evidence)

    def test_missing_chart_dependency_does_not_block_csv_profile(self):
        self.make_skill("data-lab")
        with patch.object(doctor, "probe_python", return_value=fake_probe()):
            report = self.scan(python=sys.executable)
        self.assertEqual(self.item(report, "data-lab.sum_table")["checks"]["dependencies"]["status"], "passed")
        self.assertEqual(self.item(report, "data-lab.chart")["checks"]["dependencies"]["status"], "failed")
        self.assertIsNone(self.item(report, "data-lab.sum_table")["execution_ready"])

    def test_version_outside_declared_range_fails(self):
        self.make_skill("data-lab")
        with patch.object(doctor, "probe_python", return_value=fake_probe(pandas="3.0.1")):
            report = self.scan(python=sys.executable)
        self.assertEqual(self.item(report, "data-lab.sum_table")["checks"]["dependencies"]["status"], "failed")
        evidence = self.evidence(report, "data-lab.sum_table", dependencies="passed")
        with self.assertRaises(doctor.CheckError):
            doctor.merge(report, evidence)

    def test_unsupported_pip_constraints_are_unknown_not_defaulted(self):
        folder = self.make_skill("data-lab")
        requirements = folder / "scripts/requirements.txt"
        for text in ("pandas~=2.2.0", "pandas>=2.2; python_version >= '3.11'",
                     "pandas @ https://synthetic-token@example.test/pandas.whl", "-r other-requirements.txt"):
            with self.subTest(text=text):
                requirements.write_text(text + "\n", encoding="utf-8")
                with patch.object(doctor, "probe_python", return_value=fake_probe()):
                    report = self.scan(python=sys.executable)
                item = self.item(report, "data-lab.sum_table")
                self.assertEqual(item["checks"]["dependencies"]["status"], "unknown")
                self.assertNotIn("synthetic-token", json.dumps(report))

    def test_duplicate_declared_requirements_are_combined(self):
        folder = self.make_skill("data-lab")
        (folder / "scripts/requirements.txt").write_text("pandas>=2.2\npandas<2.3\n", encoding="utf-8")
        with patch.object(doctor, "probe_python", return_value=fake_probe()):
            report = self.scan(python=sys.executable)
        self.assertEqual(self.item(report, "data-lab.sum_table")["checks"]["dependencies"]["status"], "failed")

    def test_same_context_observed_host_and_smoke_enable_only_tested_profile(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        evidence = self.evidence(report, "etf-comment-drafts-v2.draft", host_discovery="passed", smoke_test="passed")
        merged = doctor.merge(report, evidence)
        self.assertIs(self.item(merged, "etf-comment-drafts-v2.draft")["execution_ready"], True)
        self.assertIsNot(self.item(merged, "data-lab.sum_table")["execution_ready"], True)

    def test_older_pass_cannot_overwrite_a_newer_failed_smoke(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        latest = datetime.now(timezone.utc) - timedelta(minutes=5)
        failed = self.evidence(report, "etf-comment-drafts-v2.draft", host_discovery="passed", smoke_test="failed")
        failed["observed_at"] = latest.isoformat()
        report = doctor.merge(report, failed)
        self.assertIs(self.item(report, "etf-comment-drafts-v2.draft")["execution_ready"], False)
        stale = self.evidence(report, "etf-comment-drafts-v2.draft", smoke_test="passed")
        stale["observed_at"] = (latest - timedelta(hours=1)).isoformat()
        with self.assertRaises(doctor.CheckError):
            doctor.merge(report, stale)
        stale["observed_at"] = latest.isoformat()
        with self.assertRaises(doctor.CheckError):
            doctor.merge(report, stale)
        stale["observed_at"] = (latest + timedelta(minutes=1)).isoformat()
        recovered = doctor.merge(report, stale)
        self.assertIs(self.item(recovered, "etf-comment-drafts-v2.draft")["execution_ready"], True)

    def test_first_smoke_before_scan_and_before_host_observation_is_allowed(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        host = self.evidence(report, "etf-comment-drafts-v2.draft", host_discovery="passed")
        host["observed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        report = doctor.merge(report, host)
        smoke = self.evidence(report, "etf-comment-drafts-v2.draft", smoke_test="passed")
        smoke["observed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        merged = doctor.merge(report, smoke)
        item = self.item(merged, "etf-comment-drafts-v2.draft")
        self.assertIs(item["execution_ready"], True)
        self.assertLess(doctor.stamp(item["checks"]["smoke_test"]["observed_at"]), doctor.stamp(item["checks"]["host_discovery"]["observed_at"]))

    def test_future_observation_and_check_after_batch_are_rejected(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        future = self.evidence(report, "etf-comment-drafts-v2.draft", smoke_test="passed")
        future["observed_at"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with self.assertRaises(doctor.CheckError):
            doctor.merge(report, future)
        bad_batch = self.evidence(report, "etf-comment-drafts-v2.draft", smoke_test="passed")
        bad_batch["skills"][0]["checks"]["smoke_test"]["observed_at"] = datetime.now(timezone.utc).isoformat()
        with self.assertRaises(doctor.CheckError):
            doctor.merge(report, bad_batch)

    def test_confirmed_binding_survives_merge_without_repassing_bindings(self):
        self.make_skill("etf-comment-drafts-v2", "copy-a")
        self.make_skill("etf-comment-drafts-v2", "copy-b")
        bindings = {"preferred_sources": {"etf-comment-drafts-v2": "ROOT_1/copy-b/SKILL.md"}}
        report = self.scan(bindings=bindings)
        host_a = self.evidence(report, "etf-comment-drafts-v2.draft", host_discovery="passed")
        self.assertEqual(host_a["skills"][0]["source_ref"], "ROOT_1/copy-a/SKILL.md")
        merged = doctor.merge(report, host_a)
        self.assertEqual(merged["source_selection"]["etf-comment-drafts-v2"]["source_ref"], "ROOT_1/copy-b/SKILL.md")
        self.assertEqual(merged["source_bindings"], bindings)
        self.assertEqual(merged["binding_history"], report["binding_history"])
        replacement = {"preferred_sources": {"etf-comment-drafts-v2": "ROOT_1/copy-a/SKILL.md"}}
        changed = doctor.merge(merged, host_a, replacement)
        self.assertEqual(changed["source_selection"]["etf-comment-drafts-v2"]["source_ref"], "ROOT_1/copy-a/SKILL.md")
        self.assertEqual(changed["binding_history"][-1]["previous"], bindings["preferred_sources"])
        self.assertEqual(changed["binding_history"][-1]["current"], replacement["preferred_sources"])

    def test_legacy_static_confirmed_binding_is_preserved(self):
        self.make_skill("etf-comment-drafts-v2", "copy-a")
        self.make_skill("etf-comment-drafts-v2", "copy-b")
        report = self.scan(bindings={"preferred_sources": {"etf-comment-drafts-v2": "ROOT_1/copy-b/SKILL.md"}})
        del report["source_bindings"]
        host_a = self.evidence(report, "etf-comment-drafts-v2.draft", host_discovery="passed")
        merged = doctor.merge(report, host_a)
        self.assertEqual(merged["source_selection"]["etf-comment-drafts-v2"]["source_ref"], "ROOT_1/copy-b/SKILL.md")

    def test_evidence_cannot_cross_session_environment_or_fingerprint(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        for mutation in ("session", "environment", "fingerprint"):
            evidence = self.evidence(report, "etf-comment-drafts-v2.draft", host_discovery="passed")
            if mutation == "session":
                evidence["observation_context"]["session_id"] = "other-session"
            elif mutation == "environment":
                evidence["environment"]["client_version"] = "another-version"
            else:
                evidence["skills"][0]["source_fingerprint"]["files"]["SKILL.md"] = "0" * 64
            with self.subTest(mutation=mutation), self.assertRaises(doctor.CheckError):
                doctor.merge(report, evidence)

    def test_recheck_rejects_changed_source_bytes(self):
        folder = self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        (folder / "references/contrasts.md").write_text("# changed", encoding="utf-8")
        with self.assertRaises(doctor.CheckError):
            doctor.current_report(report, [self.root], None)

    def test_recheck_rejects_changed_runtime_metadata(self):
        self.make_skill("data-lab")
        with patch.object(doctor, "probe_python", return_value=fake_probe()):
            report = self.scan(python=sys.executable)
        with patch.object(doctor, "probe_python", return_value=fake_probe(pandas="3.0.1")):
            with self.assertRaises(doctor.CheckError):
                doctor.current_report(report, [self.root], sys.executable)

    def test_file_playbook_does_not_fabricate_native_discovery(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        evidence = self.evidence(report, "etf-comment-drafts-v2.draft", smoke_test="passed")
        evidence["skills"][0]["access_mode"] = "explicit_file_playbook"
        merged = doctor.merge(report, evidence)
        item = self.item(merged, "etf-comment-drafts-v2.draft")
        self.assertIs(item["execution_ready"], True)
        self.assertEqual(item["checks"]["host_discovery"]["status"], "unknown")

    def test_smoke_cannot_be_bypassed_or_statics_overridden(self):
        self.make_skill("etf-comment-drafts-v2")
        report = self.scan()
        for check_name, status in (("smoke_test", "not_applicable"), ("filesystem", "passed")):
            evidence = self.evidence(report, "etf-comment-drafts-v2.draft", **{check_name: status})
            with self.subTest(check_name=check_name), self.assertRaises(doctor.CheckError):
                doctor.merge(report, evidence)
        broken = copy.deepcopy(report)
        self.item(broken, "etf-comment-drafts-v2.draft")["execution_ready"] = True
        with self.assertRaises(doctor.CheckError):
            doctor.validate(broken)

    def test_shareable_evidence_rejects_paths_but_accepts_public_urls(self):
        doctor.public_strings("https://learn.chatgpt.com/docs/plugins")
        with self.assertRaises(doctor.CheckError):
            doctor.public_strings("\\".join(("C:", "Users", "synthetic-user", "private.json")))
        with self.assertRaises(doctor.CheckError):
            doctor.public_strings("/".join(("", "home", "synthetic-user", "private.json")))

    def test_plugin_powershell_wrapper_is_standalone_and_utf8(self):
        powershell = shutil.which("pwsh")
        if os.name != "nt" or not powershell:
            self.skipTest("Windows PowerShell 7 is not available.")
        self.make_skill("etf-comment-drafts-v2", "草稿 [公开]")
        wrapper = SCRIPT.with_suffix(".ps1")
        output = self.base / "包装器 中文.json"
        run = subprocess.run([powershell, "-NoProfile", "-File", str(wrapper), "-Roots", str(self.root),
                              "-OutputPath", str(output), "-PythonPath", sys.executable, "-SessionId", "wrapper-test"],
                             capture_output=True, text=True, encoding="utf-8", timeout=40)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(doctor.validate(doctor.read_json(output)))

    def test_powershell_auto_python_skips_store_alias_before_real_interpreter(self):
        powershell = shutil.which("pwsh")
        if os.name != "nt" or not powershell or Path(sys.executable).name.lower() != "python.exe":
            self.skipTest("Windows Python executable and PowerShell 7 are required.")
        self.make_skill("etf-comment-drafts-v2")
        aliases = self.base / "WindowsApps"
        aliases.mkdir()
        (aliases / "python.exe").write_bytes(b"")
        output = self.base / "auto-python.json"
        environment = os.environ.copy()
        environment["PATH"] = os.pathsep.join([str(aliases), str(Path(sys.executable).parent), environment.get("PATH", "")])
        run = subprocess.run([powershell, "-NoProfile", "-File", str(SCRIPT.with_suffix(".ps1")), "-Roots", str(self.root),
                              "-OutputPath", str(output), "-SessionId", "auto-python-test"],
                             capture_output=True, text=True, encoding="utf-8", timeout=40, env=environment)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(doctor.validate(doctor.read_json(output)))


if __name__ == "__main__":
    unittest.main()
