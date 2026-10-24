"""The standalone setup entry must route to environment setup without changing semantics."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or ("C:/Program Files/Git/bin/bash.exe"
                               if Path("C:/Program Files/Git/bin/bash.exe").is_file() else None)


@unittest.skipUnless(BASH, "Bash is needed for the setup wrapper")
class SetupEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3 setup ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(ROOT / "setup.sh", self.root / "setup.sh")
        (self.root / "deploy.sh").write_text(
            '#!/usr/bin/env bash\nprintf "mode=%s\\n" "$*"\nprintf "marker=%s\\n" "${H3_TEST_MARKER:-}"\nexit 7\n',
            encoding="utf-8", newline="\n")

    def run_setup(self, *args):
        # Relative path from a different working directory, including spaces.
        return subprocess.run([BASH, self.root.name + "/setup.sh", *args], cwd=self.root.parent,
                              env={**os.environ, "H3_TEST_MARKER": "forwarded"},
                              text=True, capture_output=True, timeout=10)

    def test_help_does_not_start_deployment(self):
        result = self.run_setup("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertNotIn("mode=", result.stdout)

    def test_unrecognized_arguments_are_rejected(self):
        result = self.run_setup("--download")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("mode=", result.stdout)

    def test_setup_only_environment_and_exit_code_are_forwarded(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("mode=--setup", result.stdout)
        self.assertIn("marker=forwarded", result.stdout)


if __name__ == "__main__":
    unittest.main()
