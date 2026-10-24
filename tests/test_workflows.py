"""Workflow contract, cache upgrade and acceptance failure regression tests (no GPU)."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import acceptance
import download_model
from generate import parse_args
from h3_config import (COMPONENTS, MANIFEST_SCHEMA, MODEL_ID, MODEL_PROFILE,
                       MODEL_REVISION, ROOT_CONFIGS, WEIGHT_COMPONENTS, WORKFLOWS)


class WorkflowArgumentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "image.png"
        self.video = self.root / "video.mp4"
        self.audio = self.root / "audio.wav"
        for path in (self.image, self.video, self.audio):
            path.write_bytes(b"file")

    def parse(self, *extra):
        return parse_args(["--prompt", "red ball", "--output", str(self.root / "output.mp4"), *map(str, extra)])

    def test_first_last_and_both_keyframes(self):
        for flags in [("--image", self.image), ("--last-image", self.image),
                      ("--image", self.image, "--last-image", self.image)]:
            self.assertEqual(self.parse("--workflow", "fl2va", *flags).workflow, "fl2va")

    def test_cross_modality_reference_order_is_preserved(self):
        args = self.parse("--workflow", "ref2va", "--reference", "video", self.video,
                          "--reference", "image", self.image, "--reference", "audio", self.audio)
        self.assertEqual([kind for kind, _ in args.reference], ["video", "image", "audio"])

    def test_invalid_workflow_combinations_fail_early(self):
        cases = [("--workflow", "fl2va"), ("--workflow", "ref2va"), ("--image", self.image),
                 ("--workflow", "ref2va", "--reference", "audio", self.audio),
                 ("--workflow", "ref2va", "--reference", "unknown", self.image),
                 ("--workflow", "fl2va", "--image", self.image, "--reference", "image", self.image),
                 ("--workflow", "ref2va", "--reference", "image", "https://example.com/image.png"),
                 ("--workflow", "ref2va", "--reference", "video", self.video, "--output", self.video)]
        with contextlib.redirect_stderr(io.StringIO()):
            for flags in cases:
                with self.subTest(flags=flags), self.assertRaises(SystemExit):
                    self.parse(*flags)

    def test_reference_count_limits(self):
        cases = [[("image", self.image)] * 10,
                 [("video", self.video)] * 4,
                 [("image", self.image)] + [("audio", self.audio)] * 4,
                 [("image", self.image)] * 9 + [("video", self.video)] * 3 + [("audio", self.audio)]]
        with contextlib.redirect_stderr(io.StringIO()):
            for refs in cases:
                flags = [str(part) for kind, path in refs for part in ("--reference", kind, path)]
                with self.assertRaises(SystemExit):
                    self.parse("--workflow", "ref2va", *flags)


class FullCacheTests(unittest.TestCase):
    def files(self):
        return {**{name: 2 for name in ROOT_CONFIGS},
                **{f"{name}/config.json": 2 for name in COMPONENTS},
                **{f"{name}/model.safetensors": 2 for name in WEIGHT_COMPONENTS}}

    def test_old_t2va_file_set_cannot_pass_full_manifest(self):
        files = {name: size for name, size in self.files().items() if not name.startswith("transformer_ref/")}
        with self.assertRaisesRegex(RuntimeError, "transformer_ref"):
            download_model.validate_manifest(files)

    def test_config_alone_is_not_a_complete_transformer(self):
        files = self.files()
        del files["transformer_ref/model.safetensors"]
        with self.assertRaisesRegex(RuntimeError, "Missing weights"):
            download_model.validate_manifest(files)

    def test_upgrade_reuses_previous_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self.files()
            for name in files:
                if not name.startswith("transformer_ref/"):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"{}")
            missing = download_model.missing_files(root, files)
            self.assertTrue(missing)
            self.assertTrue(all(name.startswith("transformer_ref/") for name in missing))

    def test_old_manifest_schema_rejected_even_if_renamed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"repo_id": MODEL_ID, "revision": MODEL_REVISION,
                                            "files": self.files()}))
            with patch.object(download_model, "cache_paths", return_value=(root, manifest)):
                with self.assertRaisesRegex(RuntimeError, "Full H3 manifest required"):
                    download_model.local_snapshot()


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.report_path = self.root / "acceptance.json"
        self.fixtures = {name: self.root / name for name in ("first", "last", "video", "audio")}

    def run_suite(self, full=True, side_effect=None, media_error=None):
        with patch.object(acceptance, "create_fixtures", return_value=self.fixtures), \
             patch.object(acceptance.subprocess, "run", side_effect=side_effect,
                          return_value=subprocess.CompletedProcess([], 0)) as runner, \
             patch.object(acceptance, "verify_media", side_effect=media_error), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = acceptance.run_acceptance(full=full, output=self.root / "smoke.mp4",
                                            report_path=self.report_path, prompt="red ball", timeout=60)
        return code, json.loads(self.report_path.read_text()), runner

    def test_full_suite_starts_three_separate_workflows_in_order(self):
        code, report, runner = self.run_suite()
        self.assertEqual(code, 0)
        self.assertTrue(report["all_workflows_passed"])
        self.assertEqual(list(report["workflows"]), list(WORKFLOWS))
        self.assertTrue(all(entry["status"] == "passed" for entry in report["workflows"].values()))
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertEqual([command[command.index("--workflow") + 1] for command in commands], list(WORKFLOWS))
        self.assertIn("--last-image", commands[1])
        self.assertEqual(commands[2].count("--reference"), 3)
        self.assertTrue(all(call.kwargs["env"]["HF_HUB_OFFLINE"] == "1" for call in runner.call_args_list))

    def test_quick_success_is_not_full_success(self):
        code, report, runner = self.run_suite(full=False)
        self.assertEqual(code, 0)
        self.assertFalse(report["all_workflows_passed"])
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(report["workflows"]["ref2va"]["status"], "not_run")

    def test_second_failure_stops_remaining_and_reports_partial(self):
        code, report, runner = self.run_suite(side_effect=[subprocess.CompletedProcess([], 0),
                                                         subprocess.CompletedProcess([], 5)])
        self.assertEqual(code, 5)
        self.assertFalse(report["all_workflows_passed"])
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(report["workflows"]["t2va"]["status"], "passed")
        self.assertEqual(report["workflows"]["fl2va"]["status"], "failed")
        self.assertEqual(report["workflows"]["ref2va"]["status"], "not_run")

    def test_timeout_is_failure_not_success(self):
        code, report, _ = self.run_suite(side_effect=subprocess.TimeoutExpired(["generate.py"], 60))
        self.assertEqual(code, 124)
        self.assertEqual(report["workflows"]["t2va"]["status"], "timeout")
        self.assertFalse(report["all_workflows_passed"])

    def test_zero_exit_without_valid_media_does_not_pass(self):
        code, report, _ = self.run_suite(media_error=RuntimeError("missing audio"))
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("validated_output", report["workflows"]["t2va"])

    def test_real_subprocess_deadline_is_enforced(self):
        real_run = subprocess.run
        def slow_child(command, **kwargs):
            return real_run([sys.executable, "-c", "import time; time.sleep(10)"], **kwargs)
        with patch.object(acceptance.subprocess, "run", side_effect=slow_child), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = acceptance.run_acceptance(full=False, output=self.root / "out.mp4",
                                            report_path=self.report_path, prompt="ball", timeout=0.1)
        self.assertEqual(code, 124)
        report = json.loads(self.report_path.read_text())
        self.assertEqual(report["workflows"]["t2va"]["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
