"""Release regressions: real checkouts, excluded metadata, reproducible archives."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_check", ROOT / "tools/check_package.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "Git is required to verify checkout byte preservation")
    def test_git_checkout_preserves_fingerprints_with_windows_autocrlf(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as area:
            base = Path(area)
            source, checkout = base / "source", base / "checkout"
            source.mkdir()
            (source / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
            payload = "合成插件资源\nsecond line\n".encode("utf-8")
            (source / "entry.txt").write_bytes(payload)
            def git(*args, cwd=source):
                subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=30)
            git("init", "--quiet")
            git("add", ".")
            git("-c", "user.name=Synthetic Test", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
            git("-c", "core.autocrlf=true", "clone", "--quiet", str(source), str(checkout), cwd=base)
            self.assertEqual((checkout / "entry.txt").read_bytes(), payload)

    def test_git_checkouts_and_worktrees_are_accepted_without_metadata(self):
        for directory in (True, False):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory(dir=ROOT.parent) as area:
                base = Path(area)
                (base / "README.md").write_text("Synthetic release\n", encoding="utf-8")
                if directory:
                    (base / ".git").mkdir()
                    (base / ".git/config").write_text("not an artifact", encoding="utf-8")
                else:
                    (base / ".git").write_text("gitdir: synthetic-metadata", encoding="utf-8")
                self.assertEqual([p.name for p in release.collect(base)], ["README.md"])

    def test_archives_are_reproducible_and_exclusive(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as area:
            base = Path(area)
            source = base / "source"
            source.mkdir()
            (source / "说明.md").write_text("合成发布内容\n", encoding="utf-8")
            files = release.collect(source)
            first, second = base / "one.zip", base / "two.zip"
            self.assertEqual(release.archive(first, files, source), release.archive(second, files, source))
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), ["说明.md"])
            with self.assertRaises(ValueError):
                release.archive(first, files, source)

    def test_private_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as area:
            base = Path(area)
            (base / ".env").write_text("SYNTHETIC=true\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                release.collect(base)

    def test_memory_feedback_and_setup_state_cannot_ship(self):
        for filename in ("memory.json", "feedback.json", "setup.local.json", "memory.lock", ".feedback.lock", ".setup.lock"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(dir=ROOT.parent) as area:
                base = Path(area)
                (base / "nested-state").mkdir()
                (base / "nested-state" / filename).write_text("synthetic private state", encoding="utf-8")
                with self.assertRaises(ValueError):
                    release.collect(base)

    def test_runtime_content_cannot_ship_even_when_it_is_plain_json(self):
        for directory in ("runtime", "indexes", "cache", "logs", "tmp"):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory(dir=ROOT.parent) as area:
                base = Path(area)
                (base / directory).mkdir()
                (base / directory / "generated.json").write_text("{}", encoding="utf-8")
                with self.assertRaises(ValueError):
                    release.collect(base)


if __name__ == "__main__":
    unittest.main()
