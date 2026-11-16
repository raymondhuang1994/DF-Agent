"""Observable write boundaries and off-source runtime behavior."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "plugins/df-agent/skills/df-agent/scripts/access.py"
SPEC = importlib.util.spec_from_file_location("df_agent_access_tests", SCRIPT)
access = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(access)


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="df-agent-access-", dir=PROJECT.parent)
        self.base = Path(self.temp.name)
        self.source = self.base / "documents"
        self.source.mkdir()
        (self.source / "input.txt").write_text("Synthetic business input", encoding="utf-8")
        self.runtime = self.base / "runtime"

    def tearDown(self):
        self.temp.cleanup()

    def grant(self, root=None, operations=("runtime",)):
        return access.WriteAccess("synthetic-task", [root or self.runtime], operations, [self.source])

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_layout_uses_each_users_localappdata_without_creating_it(self):
        for user in ("user-one", "user-two"):
            appdata = self.base / user
            with patch.dict(os.environ, {"LOCALAPPDATA": str(appdata)}):
                layout = access.runtime_layout()
            expected = appdata / "DF-Agent" / "runtime"
            self.assertEqual(layout["runtime_root"], str(expected))
            self.assertEqual(set(layout["paths"]), {"indexes", "cache", "logs", "tmp"})
            self.assertFalse(appdata.exists())
            self.assertFalse(layout["business_sources_accessed"])

    def test_preparation_without_grant_has_no_effects(self):
        before = sorted(self.base.rglob("*"))
        with self.assertRaises(access.AccessError):
            access.prepare_runtime(self.runtime)
        self.assertEqual(before, sorted(self.base.rglob("*")))

    def test_scoped_preparation_only_creates_runtime_directories(self):
        before = (self.source / "input.txt").read_bytes()
        result = access.prepare_runtime(self.runtime, write_access=self.grant())
        self.assertEqual(result["status"], "prepared")
        self.assertEqual({p.name for p in self.runtime.iterdir()}, set(access.RUNTIME_KINDS))
        self.assertFalse(result["files_written"])
        self.assertFalse(result["provider_configured"])
        self.assertEqual((self.source / "input.txt").read_bytes(), before)
        self.assertEqual(len(list(self.source.iterdir())), 1)
        repeated = access.prepare_runtime(self.runtime, write_access=self.grant())
        self.assertEqual(repeated["directories_created"], [])

    def test_all_runtime_destinations_checked_before_first_mkdir(self):
        self.runtime.mkdir()
        (self.runtime / "tmp").write_text("existing file", encoding="utf-8")
        with self.assertRaises(access.AccessError):
            access.prepare_runtime(self.runtime, write_access=self.grant())
        self.assertEqual([p.name for p in self.runtime.iterdir()], ["tmp"])

    def test_source_and_ancestor_write_grants_are_rejected(self):
        for target in (self.source, self.source / "index", self.base):
            with self.subTest(target=target), self.assertRaises(access.AccessError):
                self.grant(target)
        for target in (self.source, self.source / "index", self.base):
            with self.subTest(target=target), self.assertRaises(access.AccessError):
                access.runtime_layout(target, [self.source])

    def test_default_windows_document_root_cannot_be_overridden(self):
        if os.name != "nt":
            self.skipTest("Windows drive semantics")
        for root in (Path(access.DEFAULT_DOCUMENT_ROOT), Path(access.DEFAULT_DOCUMENT_ROOT) / "indexes", Path("N:/")):
            with self.subTest(root=root), self.assertRaises(access.AccessError):
                access.WriteAccess("synthetic", [root], ["runtime"], [self.source])

    def test_task_directory_and_operation_are_all_required(self):
        for task, roots, operations in (("", [self.runtime], ["runtime"]),
                                        ("task", [], ["runtime"]),
                                        ("task", [self.runtime], []),
                                        ("task", [self.runtime], ["anything"])):
            with self.subTest(task=task, roots=roots, operations=operations), self.assertRaises(access.AccessError):
                access.WriteAccess(task, roots, operations)
        with self.assertRaises(access.AccessError):
            access.require_write(self.grant(), self.runtime / "record.json", "memory")

    def test_normalized_escapes_and_sibling_prefixes_are_rejected(self):
        grant = self.grant()
        for target in (self.runtime / ".." / "escaped.json", self.base / "runtime-other" / "x.json"):
            with self.subTest(target=target), self.assertRaises(access.AccessError):
                grant.require(target, "runtime")
        self.assertEqual(grant.require(self.runtime / "indexes" / "x.db", "runtime"), self.runtime / "indexes" / "x.db")
        self.assertFalse(self.runtime.exists())

    def test_existing_hard_link_target_is_not_writable(self):
        self.runtime.mkdir()
        linked = self.runtime / "linked.txt"
        os.link(self.source / "input.txt", linked)
        with self.assertRaises(access.AccessError):
            self.grant().require(linked, "runtime")
        self.assertEqual((self.source / "input.txt").read_text("utf-8"), "Synthetic business input")

    def test_link_added_after_grant_is_rejected_at_use_time(self):
        grant = self.grant()
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(self.runtime), str(self.source)],
                           check=True, capture_output=True, timeout=30)
        else:
            self.runtime.symlink_to(self.source, target_is_directory=True)
        try:
            with self.assertRaises(access.AccessError):
                grant.require(self.runtime / "input.txt", "runtime")
        finally:
            if os.name == "nt":
                os.rmdir(self.runtime)  # Remove only this known test junction.
            else:
                self.runtime.unlink()

    def test_virtualized_root_is_rechecked_when_physical_mapping_changes(self):
        declared = self.base / "logical-runtime"
        first, current = self.base / "old-mapping", self.base / "current-mapping"
        mapping = [first]
        real_check = access.no_links

        def virtualized(path):
            if access.absolute(path) == declared:
                return mapping[0]
            return real_check(path)

        with patch.object(access, "no_links", side_effect=virtualized):
            grant = self.grant(declared)
            mapping[0] = current
            target = current / "indexes" / "index.db"
            self.assertEqual(grant.require(target, "runtime"), target)
            with self.assertRaises(access.AccessError):
                grant.require(first / "index.db", "runtime")
            mapping[0] = self.source
            with self.assertRaises(access.AccessError):
                grant.require(self.source / "input.txt", "runtime")

    def test_plugin_and_repository_are_not_runtime_storage(self):
        for target in (PROJECT, PROJECT / "runtime", SCRIPT.parent / "runtime"):
            with self.subTest(target=target), self.assertRaises(access.AccessError):
                access.runtime_layout(target)

    def test_cli_no_grant_fails_before_writing_and_layout_is_read_only(self):
        layout = self.run_cli("layout", "--runtime-root", self.runtime)
        self.assertEqual(layout.returncode, 0, layout.stderr)
        self.assertEqual(json.loads(layout.stdout)["status"], "layout")
        denied = self.run_cli("prepare", "--runtime-root", self.runtime)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("Read-only", denied.stderr)
        self.assertFalse(self.runtime.exists())
        permitted = self.run_cli("--task-id", "synthetic", "--write-root", self.runtime,
                                 "--allow-operation", "runtime", "--document-root", self.source,
                                 "prepare", "--runtime-root", self.runtime)
        self.assertEqual(permitted.returncode, 0, permitted.stderr)
        self.assertEqual(json.loads(permitted.stdout)["status"], "prepared")

    def test_partial_cli_grant_is_not_treated_as_authorization(self):
        result = self.run_cli("--write-root", self.runtime, "prepare", "--runtime-root", self.runtime)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.runtime.exists())


if __name__ == "__main__":
    unittest.main()
