"""Test actual Bash orchestration with fake heavyweight commands; never install/download weights."""

import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import preflight

ROOT = Path(__file__).resolve().parents[1]


class PreparationPreflightTests(unittest.TestCase):
    def test_prepare_does_not_probe_gpu_or_large_ram(self):
        args = ["preflight.py", "--storage-only", "--cache", "cache", "--output", "out/test.mp4",
                "--environment", ".", "--pip-cache", "pip", "--install"]
        with patch.object(sys, "argv", args), patch.object(preflight, "check_disks") as disks, \
             patch.object(preflight.subprocess, "run", side_effect=AssertionError("GPU probed")), \
             patch.object(preflight, "available_memory", side_effect=AssertionError("RAM probed")), \
             contextlib.redirect_stdout(io.StringIO()):
            preflight.main()
        self.assertEqual(len(disks.call_args.args[0]), 4)


@unittest.skipUnless(sys.platform == "linux" and shutil.which("bash"), "Bash workflow tests run on Ubuntu CI")
class HandoffWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copy(ROOT / "deploy.sh", self.root / "deploy.sh")
        shutil.copy(ROOT / "scripts/environment.sh", self.root / "scripts/environment.sh")
        self.bin = self.root / "fake-bin"
        self.bin.mkdir()
        self.trace = self.root / "commands.txt"
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith("H3_") or key in ("CUDA_VISIBLE_DEVICES", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
                del self.env[key]
        self.env.update(PATH=str(self.bin) + os.pathsep + self.env["PATH"], TRACE=str(self.trace))
        self.executable("apt-get", 'echo "UNEXPECTED APT" >> "$TRACE"; exit 88')
        self.executable("sudo", 'echo "UNEXPECTED SUDO" >> "$TRACE"; exit 88')
        self.executable("nvidia-smi", 'echo "GPU QUERY" >> "$TRACE"; echo GPU-fake')
        self.executable("ffmpeg", "exit 0")
        self.executable("ffprobe", "exit 0")
        self.fake_python = self.executable("python-fake", '''
if [[ "$1" == -c ]]; then
  if [[ "$2" == *local_snapshot* ]]; then
    echo "cache offline=${HF_HUB_OFFLINE:-0}" >> "$TRACE"
    exit "${FAIL_CACHE:-0}"
  fi
  if [[ "$2" == *"print(sys.version_info[:2])"* ]]; then echo '(3, 12)'; fi
  exit 0
fi
echo "$* offline=${HF_HUB_OFFLINE:-0}" >> "$TRACE"
if [[ "$1" == -m && "$2" == venv ]]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python"
fi
if [[ "$1" == acceptance.py ]]; then
  if [[ "${SLOW_GENERATE:-0}" == 1 ]]; then sleep 10; fi
  exit "${FAIL_GENERATE:-0}"
fi
exit 0
''')
        venv = self.root / ".venv/bin"
        venv.mkdir(parents=True)
        shutil.copy(self.fake_python, venv / "python")

    def executable(self, name, body):
        target = self.bin / name
        target.write_text("#!/usr/bin/env bash\nset -eu\n" + body + "\n")
        target.chmod(0o755)
        return target

    def run_mode(self, mode, **variables):
        return subprocess.run(["bash", "deploy.sh", *([mode] if mode else [])], cwd=self.root,
                              env={**self.env, **variables}, text=True,
                              capture_output=True, timeout=20)

    def report(self):
        reports = list((self.root / "logs").glob("*-result.txt"))
        self.assertEqual(len(reports), 1)
        return reports[0].read_text()

    def test_prepare_installs_downloads_without_gpu(self):
        result = self.run_mode("--prepare")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        trace = self.trace.read_text()
        self.assertNotIn("GPU QUERY", trace)
        self.assertIn("--storage-only", trace)
        self.assertIn("verify_runtime.py --cpu", trace)
        self.assertIn("download_model.py", trace)
        self.assertNotIn("acceptance.py", trace)
        self.assertIn("result=PASS", self.report())
        self.assertNotIn("validated_output=", self.report())

    def test_default_cold_start_installs_downloads_and_generates_in_order(self):
        (self.root / ".venv").rename(self.root / "old-venv")
        result = self.run_mode(None, H3_PYTHON=str(self.fake_python))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        trace = self.trace.read_text()
        self.assertIn("-m venv", trace)
        self.assertIn("pip install", trace)
        self.assertIn("GPU QUERY", trace)
        self.assertLess(trace.index("verify_runtime.py"), trace.index("download_model.py"))
        self.assertLess(trace.index("download_model.py"), trace.index("acceptance.py"))
        self.assertIn("mode=all", self.report())
        self.assertIn("result=PASS", self.report())
        self.assertIn("validated_acceptance_report=", self.report())
        self.assertIn("acceptance.py --scope all", trace)

    def test_test_never_installs_or_downloads(self):
        result = self.run_mode("--test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        trace = self.trace.read_text()
        self.assertIn("GPU QUERY", trace)
        self.assertIn("cache offline=1", trace)
        self.assertIn("acceptance.py", trace)
        self.assertNotIn("pip install", trace)
        self.assertNotIn("download_model.py", trace)
        self.assertNotIn("APT", trace)
        self.assertIn("validated_output=", self.report())

    def test_quick_check_does_not_load_model(self):
        result = self.run_mode("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        trace = self.trace.read_text()
        self.assertIn("cache offline=1", trace)
        self.assertNotIn("acceptance.py", trace)
        self.assertNotIn("pip install", trace)
        self.assertNotIn("validated_output=", self.report())

    def test_missing_cache_fails_before_generation_with_report(self):
        result = self.run_mode("--test", FAIL_CACHE="9")
        self.assertEqual(result.returncode, 9, result.stdout + result.stderr)
        self.assertNotIn("acceptance.py", self.trace.read_text())
        self.assertIn("last_stage=cache", self.report())
        self.assertIn("result=FAIL", self.report())

    def test_generation_failure_is_not_success(self):
        result = self.run_mode("--test", FAIL_GENERATE="7")
        self.assertEqual(result.returncode, 7)
        self.assertIn("last_stage=generation", self.report())
        self.assertNotIn("validated_output=", self.report())

    def test_generation_deadline_is_forwarded_per_workflow(self):
        result = self.run_mode("--test", H3_TEST_TIMEOUT="600")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--timeout 600", self.trace.read_text())

    def test_full_test_runs_all_workflows_without_install_or_download(self):
        result = self.run_mode("--test-all")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        trace = self.trace.read_text()
        self.assertIn("acceptance.py --scope all", trace)
        self.assertNotIn("pip install", trace)
        self.assertNotIn("download_model.py", trace)
        self.assertIn("validated_acceptance_report=", self.report())

    def test_preflight_writes_no_logs_or_locks(self):
        result = self.run_mode("--preflight")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "logs").exists())
        self.assertFalse((self.root / ".cache-deploy.lock").exists())

    def test_explicit_invalid_python_does_not_install(self):
        result = self.run_mode("--prepare", H3_PYTHON="/does/not/exist")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("last_stage=python-selection", self.report())
        self.assertFalse(self.trace.exists())

    def run_selection(self, candidates):
        # Exercise the real selection function while stubbing apt/interpreters only.
        body = '''
set -eu
source scripts/environment.sh
VENV_DIR=/nonexistent/h3-test-venv
fail() { echo "$*" >&2; exit 1; }
INSTALLED=0
supported_python() { [[ "$INSTALLED" == 1 && "$1" == python3.12 ]]; }
apt_install() { echo "apt $*"; if (($#)); then INSTALLED=1; fi; }
''' + candidates + '''
select_python 1
echo "selected=$H3_PYTHON"
'''
        return subprocess.run(["bash", "-c", body], cwd=self.root, env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_auto_install_requires_matching_venv_package(self):
        result = self.run_selection('apt-cache() { if [[ "$2" == python3.12 ]]; then echo "Candidate: 3.12.3-1"; else echo "Candidate: (none)"; fi; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("apt python", result.stdout)

    def test_auto_install_selects_final_interpreter_pair(self):
        result = self.run_selection('apt-cache() { echo "Candidate: 3.12.3-1"; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apt python3.12 python3.12-venv ca-certificates", result.stdout)
        self.assertIn("selected=python3.12", result.stdout)

    def test_auto_install_rejects_release_candidate_python(self):
        result = self.run_selection('apt-cache() { echo "Candidate: 3.11.0~rc1-1~22.04.1"; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("apt python", result.stdout)


if __name__ == "__main__":
    unittest.main()
