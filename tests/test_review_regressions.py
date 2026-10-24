"""Regression evidence from the deployment review; no GPU or model downloads."""

import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import acceptance
import download_model
from h3_config import MANIFEST_SCHEMA, MODEL_ID, MODEL_PROFILE, MODEL_REVISION
import preflight
from process_runner import cancellation_signals, run_generation, TerminationRequested


class EarlyValidationTests(unittest.TestCase):
    def test_invalid_output_or_prompt_fails_before_gpu_probe(self):
        for output, prompt in (("result.avi", "ok"), ("result.mp4", "  ")):
            args = ["preflight.py", "--gpu", "GPU-test", "--cache", "cache", "--output", output,
                    "--prompt", prompt, "--environment", ".", "--pip-cache", "pip"]
            with patch.object(sys, "argv", args), patch.object(preflight.subprocess, "run") as probe:
                with self.assertRaises(ValueError):
                    preflight.main()
                probe.assert_not_called()

    def test_output_cannot_be_directory_or_have_file_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dir.mp4").mkdir()
            (root / "file").write_bytes(b"data")
            for path in (root / "dir.mp4", root / "file/output.mp4"):
                with self.assertRaises((ValueError, RuntimeError)):
                    preflight.validate_output(path, "valid")


class ManifestRecoveryTests(unittest.TestCase):
    def test_malformed_manifest_has_recovery_message(self):
        header = {"repo_id": MODEL_ID, "revision": MODEL_REVISION,
                  "schema": MANIFEST_SCHEMA, "profile": MODEL_PROFILE}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            for value in ("{", "[]", "null", json.dumps(header),
                          json.dumps({**header, "files": []})):
                manifest.write_text(value)
                with self.subTest(value=value), patch.object(download_model, "cache_paths", return_value=(root, manifest)):
                    with self.assertRaisesRegex(RuntimeError, "--download"):
                        download_model.local_snapshot()

    def test_malformed_file_map_types_are_rejected(self):
        for files in ([], ["transformer/x"], {"transformer/x": True}, {None: 1}):
            with self.subTest(files=files), self.assertRaisesRegex(RuntimeError, "Invalid model"):
                download_model.validate_manifest(files)


class FreshOutputTests(unittest.TestCase):
    def test_old_output_cannot_satisfy_new_zero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "old.mp4"
            output.write_bytes(b"previous valid result")
            with patch.object(acceptance, "run_generation", return_value=subprocess.CompletedProcess([], 0)), \
                 patch.object(acceptance, "verify_media") as verify, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = acceptance.run_acceptance(full=False, output=output, report_path=root / "report.json",
                                                prompt="valid", timeout=0)
                verify.assert_not_called()
            self.assertEqual(code, 1)
            self.assertEqual(output.read_bytes(), b"previous valid result")
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["workflows"]["t2va"]["status"], "failed")
            self.assertFalse(list(root.glob(".h3-quick-*")))

    def test_parent_media_failure_preserves_old_output(self):
        def child(command, **kwargs):
            Path(command[command.index("--output") + 1]).write_bytes(b"invalid new result")
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "old.mp4"
            output.write_bytes(b"previous")
            with patch.object(acceptance, "run_generation", side_effect=child), \
                 patch.object(acceptance, "verify_media", side_effect=RuntimeError("invalid media")), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = acceptance.run_acceptance(full=False, output=output, report_path=root / "report.json",
                                                prompt="valid", timeout=0)
            self.assertEqual(code, 1)
            self.assertEqual(output.read_bytes(), b"previous")
            self.assertFalse(list(root.glob(".h3-quick-*")))

    def test_report_path_cannot_overwrite_video(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.mp4"
            path.write_bytes(b"previous")
            with self.assertRaisesRegex(ValueError, "different paths"):
                acceptance.run_acceptance(full=False, output=path, report_path=path, prompt="valid", timeout=0)
            self.assertEqual(path.read_bytes(), b"previous")


class CancellationTests(unittest.TestCase):
    def test_signal_handlers_restore_after_context(self):
        old = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(TerminationRequested):
            with cancellation_signals():
                signal.raise_signal(signal.SIGTERM)
        self.assertIs(signal.getsignal(signal.SIGTERM), old)

    def test_cancel_marks_active_and_unstarted_workflows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = {name: root / name for name in ("first", "last", "video", "audio")}
            with patch.object(acceptance, "create_fixtures", return_value=fixtures), \
                 patch.object(acceptance, "run_generation", side_effect=TerminationRequested(signal.SIGTERM)), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = acceptance.run_acceptance(full=True, output=root / "result.mp4",
                                                report_path=root / "report.json", prompt="valid", timeout=0)
            self.assertEqual(code, 143)
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["workflows"]["t2va"]["status"], "cancelled")
            self.assertEqual(report["workflows"]["ref2va"]["status"], "not_run")
            self.assertFalse(report["all_workflows_passed"])

    @unittest.skipUnless(sys.platform == "linux", "Process groups are the Linux deployment contract")
    def test_real_sigterm_reaps_generator_and_finishes_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_pid = root / "child.pid"
            script = root / "supervisor.py"
            script.write_text('''import sys
from pathlib import Path
import acceptance
original = acceptance.run_generation
def child(command, **kwargs):
    code = "import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    return original([sys.executable, "-c", code, sys.argv[1]], **kwargs)
acceptance.run_generation = child
raise SystemExit(acceptance.run_acceptance(full=False, output=Path(sys.argv[2]), report_path=Path(sys.argv[3]), prompt="valid", timeout=0))
''')
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            supervisor = subprocess.Popen([sys.executable, str(script), str(child_pid),
                                           str(root / "result.mp4"), str(root / "report.json")],
                                          env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 10
                while not child_pid.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(child_pid.exists(), "Generator did not start")
                pid = int(child_pid.read_text())
                supervisor.terminate()
                self.assertEqual(supervisor.wait(timeout=5), 143)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
                report = json.loads((root / "report.json").read_text())
                self.assertEqual(report["workflows"]["t2va"]["status"], "cancelled")
            finally:
                if supervisor.poll() is None:
                    supervisor.kill()
                    supervisor.wait()
                if child_pid.exists():
                    try:
                        os.kill(int(child_pid.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    @unittest.skipUnless(sys.platform == "linux", "Process groups are the Linux deployment contract")
    def test_timeout_also_stops_grandchild(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "descendant.pid"
            child = "import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(30)"
            with self.assertRaises(subprocess.TimeoutExpired):
                run_generation([sys.executable, "-c", parent, child, str(pid_file)],
                               env=os.environ.copy(), timeout=1)
            self.assertTrue(pid_file.exists())
            pid = int(pid_file.read_text())
            # A killed orphan can briefly remain as a zombie until init reaps it.
            state = Path(f"/proc/{pid}/stat")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    if state.read_text().split()[2] == "Z":
                        break
                except FileNotFoundError:
                    break
                time.sleep(0.02)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.fail("Grandchild still running after process-group timeout cleanup")


if __name__ == "__main__":
    unittest.main()
