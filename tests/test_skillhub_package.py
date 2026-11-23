"""Exercise actual archives in standalone and plugin layouts, using synthetic state."""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skillhub_release", ROOT / "tools/check_package.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class SkillHubPackageTests(unittest.TestCase):
    def exercise(self, standalone):
        source = ROOT / (release.SKILL if standalone else release.PLUGIN)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            archive = base / "distribution.skill"
            release.archive(archive, release.collect(source), source)
            installed = base / ".codex" / ("skills/df-agent" if standalone else "plugins/df-agent")
            with zipfile.ZipFile(archive) as bundle:
                if standalone:
                    self.assertIn("SKILL.md", bundle.namelist())
                    self.assertEqual(sum(Path(p).name.casefold() == "skill.md" for p in bundle.namelist()), 1)
                    self.assertIn("references/handoff.md", bundle.namelist())
                    self.assertIn("scripts/doctor.py", bundle.namelist())
                bundle.extractall(installed)
            skill = installed if standalone else installed / "skills/df-agent"
            def snapshot():
                return {p.relative_to(installed).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in installed.rglob("*") if p.is_file()}
            before = snapshot()
            program = '''
import sys
from pathlib import Path
skill, package, state = map(Path, sys.argv[1:])
sys.path.insert(0, str(skill / 'scripts'))
import access, setup, memory, feedback
assert access.package_boundaries() == [package.resolve()]
assert access.runtime_layout(state / 'runtime')['files_written'] is False
assert setup.external(state / 'setup') == (state / 'setup').resolve()
assert feedback.external_path(state / 'feedback.json') == (state / 'feedback.json').resolve()
grant = memory.access.WriteAccess('synthetic-package', [state], ['memory'])
memory.MemoryStore(state / 'memory', write_access=grant).init()
assert (state / 'memory/memory.json').is_file()
for function, error in (
    (access.runtime_layout, access.AccessError),
    (setup.external, setup.doctor.CheckError),
    (memory.MemoryStore, memory.MemoryError),
    (feedback.external_path, feedback.FeedbackError),
):
    try:
        function(package / 'state')
    except error:
        pass
    else:
        raise AssertionError('Package state was accepted')
print('package-boundaries-and-state-passed')
'''
            # The sibling directory detects an incorrectly inferred .codex boundary.
            state = base / ".codex" / "synthetic-state"
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", program,
                                     str(skill), str(installed), str(state)],
                                    capture_output=True, text=True, timeout=30,
                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("package-boundaries-and-state-passed", result.stdout)
            self.assertEqual(snapshot(), before)

    def test_standalone_package_keeps_resources_and_state_outside_it(self):
        self.exercise(standalone=True)

    def test_plugin_package_keeps_original_boundary(self):
        self.exercise(standalone=False)


if __name__ == "__main__":
    unittest.main()
