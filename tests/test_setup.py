"""Persistent onboarding: independent processes, drift, safe state and exact binding."""
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

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "plugins/team-advisor-entry/skills/team-advisor/scripts/setup.py"
SPEC = importlib.util.spec_from_file_location("advisor_setup", SCRIPT)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def fake_probe():
    return {"python": [3, 12, 14], "implementation": "CPython", "packages": {"pandas": "2.3.3"}}


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="advisor-setup-")
        self.base = Path(self.tmp.name)
        self.root = self.base / "approved skills [合成]"
        self.root.mkdir()
        self.state = self.base / "private state"
        self.make_skill("etf-comment-drafts-v2")

    def tearDown(self):
        self.tmp.cleanup()

    def make_skill(self, directory):
        skill = self.root / directory
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: etf-comment-drafts-v2\ndescription: Synthetic only\n---\n", encoding="utf-8")
        (skill / "references").mkdir()
        for name in ("contrasts.md", "private-library.md"):
            (skill / "references" / name).write_text("Synthetic reference\n", encoding="utf-8")
        return skill

    def make_plan(self, **kwargs):
        with patch.object(setup.doctor, "probe_python", return_value=fake_probe()):
            return setup.make_plan(self.state, [self.root], sys.executable, **kwargs)

    def apply(self, plan):
        with patch.object(setup.doctor, "probe_python", return_value=fake_probe()):
            return setup.apply_plan(self.state, plan)

    def test_plan_is_read_only_and_missing_optional_skills_do_not_block(self):
        plan = self.make_plan()
        self.assertFalse(self.state.exists())
        self.assertEqual(plan["config"]["bindings"]["preferred_sources"], {"etf-comment-drafts-v2": "ROOT_1/etf-comment-drafts-v2/SKILL.md"})
        result = self.apply(plan)
        self.assertEqual(result["status"], "configured")
        self.assertEqual(result["host_discovery"], "not_checked")
        self.assertEqual(plan["capabilities"]["source_selection"]["data-lab"]["status"], "unavailable")

    def test_second_process_reuses_bindings_and_reports_source_drift(self):
        plan_path = self.base / "plan.local.json"
        def run(*args):
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), *map(str, args)], capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        run("plan", "--state-dir", self.state, "--roots", self.root, "--python", sys.executable, "--output", plan_path)
        run("apply", "--state-dir", self.state, "--plan", plan_path)
        before = (self.state / setup.CONFIG_NAME).read_bytes()
        result = run("status", "--state-dir", self.state, "--session-id", "new-session")
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["bindings"]["preferred_sources"]["etf-comment-drafts-v2"], "ROOT_1/etf-comment-drafts-v2/SKILL.md")
        selected = next(item for item in result["capabilities"]["skills"] if item["skill_id"] == "etf-comment-drafts-v2")
        self.assertEqual(selected["checks"]["host_discovery"]["status"], "unknown")
        self.assertIsNone(selected["execution_ready"])
        (self.root / "etf-comment-drafts-v2/SKILL.md").write_text("---\nname: etf-comment-drafts-v2\ndescription: Changed synthetic version\n---\n", encoding="utf-8")
        result = run("status", "--state-dir", self.state)
        self.assertEqual(result["status"], "changed")
        self.assertIn("sources", result["changed_components"])
        self.assertEqual((self.state / setup.CONFIG_NAME).read_bytes(), before)

    def test_explicit_binding_resolves_duplicates_and_remains_pinned(self):
        self.make_skill("alternative")
        with self.assertRaisesRegex(setup.doctor.CheckError, "explicit preferred_sources"):
            self.make_plan()
        plan = self.make_plan(bindings={"preferred_sources": {"etf-comment-drafts-v2": "ROOT_1/alternative/SKILL.md"}})
        self.apply(plan)
        self.make_skill("third")
        with patch.object(setup.doctor, "probe_python", return_value=fake_probe()):
            result = setup.status(self.state)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["bindings"]["preferred_sources"]["etf-comment-drafts-v2"], "ROOT_1/alternative/SKILL.md")
        renewed = self.make_plan()
        self.assertEqual(renewed["config"]["bindings"]["preferred_sources"]["etf-comment-drafts-v2"], "ROOT_1/alternative/SKILL.md")

    def test_missing_pinned_source_does_not_fall_back_to_another_copy(self):
        self.apply(self.make_plan())
        self.make_skill("alternative")
        (self.root / "etf-comment-drafts-v2/SKILL.md").unlink()
        with patch.object(setup.doctor, "probe_python", return_value=fake_probe()):
            report = setup.status(self.state)
        selection = report["capabilities"]["source_selection"]["etf-comment-drafts-v2"]
        self.assertEqual(selection["reason"], "binding_not_found_or_unreadable")
        self.assertIsNone(selection["source_ref"])
        self.assertEqual(report["status"], "changed")

    def test_stale_plan_rejected_if_source_or_runtime_changes(self):
        plan = self.make_plan()
        changed_probe = fake_probe()
        changed_probe["packages"]["pandas"] = "3.0.1"
        with patch.object(setup.doctor, "probe_python", return_value=changed_probe):
            with self.assertRaisesRegex(setup.doctor.CheckError, "changed after planning"):
                setup.apply_plan(self.state, plan)
        self.assertFalse(self.state.exists())
        (self.root / "etf-comment-drafts-v2/references/contrasts.md").write_text("New content\n", encoding="utf-8")
        with self.assertRaisesRegex(setup.doctor.CheckError, "changed after planning"):
            self.apply(plan)

    def test_replayed_plan_does_not_replace_newer_configuration(self):
        plan = self.make_plan()
        self.apply(plan)
        original = (self.state / setup.CONFIG_NAME).read_bytes()
        with self.assertRaisesRegex(setup.doctor.CheckError, "configuration changed"):
            self.apply(plan)
        self.assertEqual((self.state / setup.CONFIG_NAME).read_bytes(), original)
        replacement = self.make_plan()
        self.assertEqual(replacement["config"]["revision"], 2)
        self.assertEqual(self.apply(replacement)["revision"], 2)

    def test_existing_writer_lock_prevents_config_change(self):
        plan = self.make_plan()
        self.state.mkdir()
        (self.state / ".setup.lock").write_text("synthetic other writer", encoding="utf-8")
        with self.assertRaisesRegex(setup.doctor.CheckError, "setup lock"):
            self.apply(plan)
        self.assertFalse((self.state / setup.CONFIG_NAME).exists())
        self.assertTrue((self.state / ".setup.lock").exists())

    def test_failed_atomic_replace_preserves_previous_configuration(self):
        self.apply(self.make_plan())
        original = (self.state / setup.CONFIG_NAME).read_bytes()
        update = self.make_plan()
        with patch.object(setup.os, "replace", side_effect=OSError("Synthetic interrupted save")):
            with self.assertRaises(OSError):
                self.apply(update)
        self.assertEqual((self.state / setup.CONFIG_NAME).read_bytes(), original)
        self.assertFalse((self.state / ".setup.lock").exists())
        self.assertEqual(list(self.state.glob("*.tmp")), [])

    def test_state_and_plan_cannot_be_in_release_or_skill_source(self):
        for destination in (PROJECT / "local-state", SCRIPT.parent / "local-state", self.root / "state"):
            with patch.object(setup.doctor, "probe_python", return_value=fake_probe()):
                with self.assertRaises(setup.doctor.CheckError):
                    setup.make_plan(destination, [self.root], sys.executable)
        plan = self.make_plan()
        with self.assertRaises(setup.doctor.CheckError):
            setup.write_private_output(PROJECT / "plan.local.json", plan, self.state, [self.root])
        with self.assertRaises(setup.doctor.CheckError):
            setup.write_private_output(self.state / "plan.local.json", plan, self.state, [self.root])

    def test_tampered_plan_and_wrong_state_are_rejected(self):
        plan = self.make_plan()
        modified = copy.deepcopy(plan)
        modified["config"]["python"] = "unapproved executable"
        with self.assertRaisesRegex(setup.doctor.CheckError, "Setup plan changed"):
            self.apply(modified)
        with self.assertRaises(setup.doctor.CheckError):
            setup.apply_plan(self.base / "another-state", plan)

    def test_status_before_setup_has_no_side_effects(self):
        self.assertEqual(setup.status(self.state)["status"], "not_configured")
        self.assertFalse(self.state.exists())

    def test_invalid_runtime_is_not_saved(self):
        for probe in ({"error": "interpreter_not_found"}, {"python": [3, 10, 9]}, {"python": "3.12"}):
            with patch.object(setup.doctor, "probe_python", return_value=probe):
                with self.assertRaises(setup.doctor.CheckError):
                    setup.make_plan(self.state, [self.root], sys.executable)
        self.assertFalse(self.state.exists())

    def test_default_windows_state_and_saved_python_work_from_new_shell(self):
        powershell = shutil.which("pwsh")
        if os.name != "nt" or not powershell:
            self.skipTest("Native Windows PowerShell not available")
        appdata = self.base / "isolated local appdata"
        state = appdata / "TeamAdvisor"
        plan = setup.make_plan(state, [self.root], sys.executable)
        setup.apply_plan(state, plan)
        env = dict(os.environ, LOCALAPPDATA=str(appdata))
        result = subprocess.run([powershell, "-NoProfile", "-File", str(PROJECT / "scripts/setup.ps1"), "-Action", "Status"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["state_dir"], str(state))
        self.assertEqual(report["python"], str(Path(sys.executable)))
        self.assertEqual(report["status"], "unchanged")

    def test_windows_state_junction_is_rejected_before_config_read(self):
        powershell = shutil.which("pwsh")
        if os.name != "nt" or not powershell:
            self.skipTest("Native Windows PowerShell not available")
        outside = self.base / "other-state"
        outside.mkdir()
        (outside / setup.CONFIG_NAME).write_text("unreadable synthetic JSON", encoding="utf-8")
        helper = self.base / "create-junction.ps1"
        helper.write_text("param([string]$LinkPath,[string]$TargetPath)\nNew-Item -ItemType Junction -Path $LinkPath -Target $TargetPath | Out-Null\n", encoding="utf-8")
        linked = subprocess.run([powershell, "-NoProfile", "-File", str(helper), "-LinkPath", str(self.state), "-TargetPath", str(outside)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(linked.returncode, 0, linked.stderr)
        try:
            run = subprocess.run([powershell, "-NoProfile", "-File", str(PROJECT / "scripts/setup.ps1"), "-Action", "Status", "-StateDir", str(self.state), "-PythonPath", sys.executable], capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("must not traverse links", run.stderr)
            with self.assertRaises(setup.doctor.CheckError):
                setup.status(self.state)
        finally:
            os.rmdir(self.state)  # Removes this tested junction only, not its target.


if __name__ == "__main__":
    unittest.main()
