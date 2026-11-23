"""Synthetic regressions for reader install drift and format-specific readiness."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/df-agent/skills/df-agent/scripts"

def load_script(name):
    spec = importlib.util.spec_from_file_location("detection_" + name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

doctor = load_script("doctor")
setup = load_script("setup")


def probe(openpyxl=None):
    return {"python": [3, 12, 14], "implementation": "CPython", "packages": {
        "pandas": "2.3.3", "numpy": "2.3.5", "tzdata": "2026.6", "openpyxl": openpyxl,
        "matplotlib": None, "scipy": None, "scikit-learn": None, "python-docx": None}}


class ReaderDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="df-detection-synthetic-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_skill(self, name):
        folder = self.root / name
        folder.mkdir()
        (folder / "SKILL.md").write_bytes(
            ("---\nname: " + name + "\ndescription: Synthetic only\n---\n").encode())
        resources = set()
        for profile, definition in doctor.PROFILES.items():
            if profile.rsplit(".", 1)[0] == name:
                resources.update(definition["resources"])
        if name == "data-lab":
            resources.update(doctor.DATALAB_CORE)
        if name == "df-mcp":
            resources.update(("runtime/python/team_drive/engine.py", "runtime/python/team_drive/fs_access.py",
                              "runtime/python/team_drive/extract.py", "runtime/python/vendor/parser.py"))
        for relative in resources:
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"raise RuntimeError('Synthetic code must never execute')\n" if target.suffix == ".py" else b"Synthetic reference\n")
        if name == "df-mcp":
            manifest = {"schema": "df-mcp-skill-package-v1", "files": [
                {"path": p.relative_to(folder).as_posix(), "bytes": len(p.read_bytes()), "sha256": doctor.digest(p.read_bytes())}
                for p in sorted(folder.rglob("*")) if p.is_file()]}
            (folder / "PACKAGE_MANIFEST.json").write_bytes(json.dumps(manifest).encode())
        return folder

    def scan(self, input_format=None):
        with patch.object(doctor, "probe_python", return_value=probe()):
            return doctor.scan([self.root], sys.executable, session_id="synthetic", input_format=input_format)

    def item(self, report, profile="df-mcp.lookup"):
        return next(item for item in report["skills"] if item["task_profile"] == profile)

    def test_matching_manifest_does_not_claim_reader_execution(self):
        self.make_skill("df-mcp")
        report = self.scan()
        item = self.item(report)
        self.assertEqual(item["checks"]["resource_access"]["status"], "passed")
        self.assertEqual(item["checks"]["dependencies"]["status"], "unknown")
        self.assertIsNone(item["execution_ready"])
        self.assertTrue(doctor.validate(report))

    def test_core_change_without_manifest_change_invalidates_fingerprint(self):
        folder = self.make_skill("df-mcp")
        before = self.scan()
        manifest_before = (folder / "PACKAGE_MANIFEST.json").read_bytes()
        (folder / "runtime/python/team_drive/engine.py").write_bytes(b"# Changed core\n")
        after = self.scan()
        self.assertEqual((folder / "PACKAGE_MANIFEST.json").read_bytes(), manifest_before)
        self.assertNotEqual(self.item(before)["source_fingerprint"], self.item(after)["source_fingerprint"])
        self.assertEqual(self.item(after)["checks"]["resource_access"]["status"], "failed")
        self.assertIs(self.item(after)["execution_ready"], False)
        with patch.object(doctor, "probe_python", return_value=probe()):
            with self.assertRaisesRegex(doctor.CheckError, "resources changed"):
                doctor.current_report(before, [self.root], sys.executable)

    def test_vendor_change_is_detected(self):
        folder = self.make_skill("df-mcp")
        (folder / "runtime/python/vendor/parser.py").write_bytes(b"# Changed vendor\n")
        self.assertEqual(self.item(self.scan())["checks"]["resource_access"]["status"], "failed")

    def test_missing_manifest_file_fails(self):
        folder = self.make_skill("df-mcp")
        (folder / "runtime/python/team_drive/extract.py").unlink()
        self.assertEqual(self.item(self.scan())["checks"]["resource_access"]["status"], "failed")

    def test_unlisted_runtime_code_changes_fingerprint_and_fails(self):
        folder = self.make_skill("df-mcp")
        for suffix in (".py", ".PY"):
            with self.subTest(suffix=suffix):
                path = folder / ("runtime/python/vendor/extra" + suffix)
                path.write_bytes(b"# Unlisted importable code\n")
                item = self.item(self.scan())
                self.assertEqual(item["checks"]["resource_access"]["status"], "failed")
                self.assertIn(path.relative_to(folder).as_posix(), item["source_fingerprint"]["files"])
                path.unlink()

    def test_manifest_cannot_expand_reads_above_skill_root(self):
        folder = self.make_skill("df-mcp")
        secret = self.root / "secret.txt"
        secret.write_bytes(b"Never read this source")
        manifest = {"schema": "df-mcp-skill-package-v1", "files": [{
            "path": "../secret.txt", "bytes": 22, "sha256": "a" * 64}]}
        (folder / "PACKAGE_MANIFEST.json").write_bytes(json.dumps(manifest).encode())
        observed = []
        original = doctor.read_bytes
        def read(path):
            observed.append(Path(path).resolve())
            return original(path)
        with patch.object(doctor, "read_bytes", side_effect=read):
            item = self.item(self.scan())
        self.assertNotIn(secret.resolve(), observed)
        self.assertEqual(item["checks"]["resource_access"]["status"], "failed")

    def test_missing_manifest_stays_unknown(self):
        folder = self.make_skill("df-mcp")
        (folder / "PACKAGE_MANIFEST.json").unlink()
        item = self.item(self.scan())
        self.assertEqual(item["checks"]["resource_access"]["status"], "unknown")
        self.assertIsNone(item["execution_ready"])

    def test_data_lab_csv_and_tsv_do_not_require_openpyxl(self):
        self.make_skill("data-lab")
        for input_format in ("csv", "tsv"):
            with self.subTest(input_format=input_format):
                item = self.item(self.scan(input_format), "data-lab.sum_table")
                self.assertEqual(item["checks"]["dependencies"]["status"], "passed")
                self.assertIsNone(item["execution_ready"])

    def test_data_lab_xlsx_requires_openpyxl(self):
        self.make_skill("data-lab")
        item = self.item(self.scan("xlsx"), "data-lab.sum_table")
        self.assertEqual(item["checks"]["dependencies"]["status"], "failed")
        self.assertIs(item["execution_ready"], False)

    def test_unspecified_format_stays_unknown_with_metadata_present(self):
        self.make_skill("data-lab")
        item = self.item(self.scan(), "data-lab.sum_table")
        self.assertEqual(item["checks"]["dependencies"]["status"], "unknown")
        self.assertIsNone(item["execution_ready"])

    def test_xlsx_metadata_does_not_claim_smoke_test(self):
        self.make_skill("data-lab")
        with patch.object(doctor, "probe_python", return_value=probe("3.1.5")):
            report = doctor.scan([self.root], sys.executable, session_id="synthetic", input_format="xlsx")
        item = self.item(report, "data-lab.sum_table")
        self.assertEqual(item["checks"]["dependencies"]["status"], "passed")
        self.assertEqual(item["checks"]["smoke_test"]["status"], "not_checked")
        self.assertIsNone(item["execution_ready"])

    def test_csv_evidence_cannot_authorize_xlsx_even_if_context_is_copied(self):
        self.make_skill("data-lab")
        report = self.scan("xlsx")
        item = self.item(report, "data-lab.sum_table")
        evidence = {"environment": copy.deepcopy(report["environment"]),
                    "observation_context": copy.deepcopy(report["observation_context"]),
                    "task_input_format": "csv",
                    "observed_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
                    "skills": [{"source_ref": item["source_ref"], "task_profile": item["task_profile"],
                                "source_fingerprint": item["source_fingerprint"],
                                "checks": {"smoke_test": doctor.check("passed", "Synthetic CSV run")}}]}
        with self.assertRaisesRegex(doctor.CheckError, "input format mismatch"):
            doctor.merge(report, evidence)

    def test_core_change_reaches_existing_setup_fingerprint(self):
        folder = self.make_skill("df-mcp")
        before = setup.fingerprint(self.scan())
        (folder / "runtime/python/team_drive/engine.py").write_bytes(b"# Changed reader\n")
        after = setup.fingerprint(self.scan())
        self.assertNotEqual(before["sources"], after["sources"])

    def test_legacy_scan_signature_remains_valid(self):
        self.make_skill("data-lab")
        with patch.object(doctor, "probe_python", return_value=probe()):
            report = doctor.scan([self.root], sys.executable, None, "legacy", None)
        self.assertIsNone(report["task_input_format"])
        self.assertTrue(doctor.validate(report))

    def test_powershell_passes_input_format(self):
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell not available")
        self.make_skill("data-lab")
        for wrapper in (SCRIPTS / "doctor.ps1", ROOT / "scripts/doctor.ps1"):
            with self.subTest(wrapper=wrapper.relative_to(ROOT).as_posix()):
                result = subprocess.run([powershell, "-NoProfile", "-File", str(wrapper),
                                         "-Roots", str(self.root), "-PythonPath", sys.executable,
                                         "-InputFormat", "xlsx", "-SessionId", "synthetic-wrapper"],
                                        capture_output=True, text=True, encoding="utf-8", timeout=40)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["task_input_format"], "xlsx")


if __name__ == "__main__":
    unittest.main()
