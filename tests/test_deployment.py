"""Regression tests for failure cases; no model downloads or GPU required."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import download_model
from generate import parse_args
from h3_config import (COMPONENTS, GIB, MODEL_ID, MODEL_REVISION, ROOT_CONFIGS,
                       MANIFEST_SCHEMA, MODEL_PROFILE, WEIGHT_COMPONENTS)
import preflight
from verify_media import write_verified_video


class ArgumentTests(unittest.TestCase):
    def args(self, *extra):
        return parse_args(["--prompt", "a fox", "--output", "test.mp4", *extra])

    def test_supported_duration_grid(self):
        accepted = []
        with contextlib.redirect_stderr(io.StringIO()):
            for frames in range(100, 380):
                try:
                    self.args("--frames", str(frames))
                    accepted.append(frames)
                except SystemExit:
                    pass
        self.assertEqual(accepted, list(range(124, 346, 17)))

    def test_invalid_requests_fail_before_import_or_download(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for options in [("--width", "961"), ("--height", "0"), ("--steps", "1"),
                            ("--seed", "-1"), ("--seed", str(2**63)),
                            ("--prompt", "  "), ("--output", "movie.avi")]:
                with self.subTest(options=options), self.assertRaises(SystemExit):
                    self.args(*options)

    def test_defaults_are_valid(self):
        args = self.args()
        self.assertEqual((args.width, args.height, args.frames, args.steps), (960, 544, 124, 9))


class CacheTests(unittest.TestCase):
    def files(self):
        return {**{name: 2 for name in ROOT_CONFIGS},
                **{f"{name}/config.json": 2 for name in COMPONENTS},
                **{f"{name}/model.safetensors": 2 for name in WEIGHT_COMPONENTS}}

    def test_excludes_duplicate_formats_but_includes_both_transformers(self):
        for name in ["FL2VA/model.safetensors", "Ref2VA/model.safetensors",
                     "scripts/run.py", "README.md",
                     "transformer/../../escape", "/transformer/x", "transformer\\x"]:
            with self.subTest(name=name):
                self.assertFalse(download_model.selected_file(name))
        self.assertTrue(download_model.selected_file("transformer/model-00001.safetensors"))
        self.assertTrue(download_model.selected_file("transformer_ref/model-00001.safetensors"))

    def test_incomplete_snapshot_is_not_treated_as_downloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "transformer").mkdir()
            (root / "transformer/model.safetensors").write_bytes(b"x")
            expected = {"transformer/model.safetensors": 4, "text_encoder/config.json": 2}
            self.assertEqual(download_model.missing_files(root, expected), expected)

    def test_manifest_requires_all_components(self):
        files = self.files()
        download_model.validate_manifest(files)
        del files["scheduler/config.json"]
        with self.assertRaisesRegex(RuntimeError, "Missing component"):
            download_model.validate_manifest(files)

    def test_unknown_size_is_rejected(self):
        files = self.files()
        files["vae/config.json"] = None
        with self.assertRaisesRegex(RuntimeError, "Invalid"):
            download_model.validate_manifest(files)

    def test_offline_manifest_rejects_deleted_and_changed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            files = self.files()
            for name in files:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"{}")
            manifest.write_text(json.dumps({"repo_id": MODEL_ID, "revision": MODEL_REVISION, "files": files,
                                              "schema": MANIFEST_SCHEMA, "profile": MODEL_PROFILE}))
            with patch.object(download_model, "cache_paths", return_value=(root, manifest)):
                self.assertEqual(download_model.local_snapshot(), root.resolve())
                (root / "vae/config.json").write_bytes(b"{")
                with self.assertRaisesRegex(RuntimeError, "incomplete"):
                    download_model.local_snapshot()
                (root / "vae/config.json").unlink()
                with self.assertRaisesRegex(RuntimeError, "incomplete"):
                    download_model.local_snapshot()

    def test_directory_alone_is_not_an_offline_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(download_model, "cache_paths", return_value=(root, root / "absent.json")):
                with self.assertRaisesRegex(RuntimeError, "manifest missing"):
                    download_model.local_snapshot()


class MemoryAndDiskTests(unittest.TestCase):
    def test_parent_cgroup_limit_is_honored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = root / "parent/child"
            group.mkdir(parents=True)
            membership = root / "membership"
            membership.write_text("0::/parent/child\n")
            (root / "memory.max").write_text("max")
            (root / "memory.current").write_text("0")
            (group / "memory.max").write_text("max")
            (group / "memory.current").write_text("0")
            (group.parent / "memory.max").write_text(str(160 * GIB))
            (group.parent / "memory.current").write_text(str(20 * GIB))
            self.assertEqual(min(preflight.cgroup_remaining(root, membership)), 140 * GIB)

    def test_cgroup_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = root / "memory/job"
            group.mkdir(parents=True)
            membership = root / "membership"
            membership.write_text("3:memory:/job\n")
            (group / "memory.limit_in_bytes").write_text(str(80 * GIB))
            (group / "memory.usage_in_bytes").write_text(str(10 * GIB))
            self.assertEqual(min(preflight.cgroup_remaining(root, membership)), 70 * GIB)

    def test_budgets_on_same_disk_are_added(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            usage = type("Usage", (), {"free": 25 * GIB})()
            with patch.object(preflight.shutil, "disk_usage", return_value=usage):
                with self.assertRaisesRegex(RuntimeError, "need 30.0"):
                    preflight.check_disks([(root / "cache", 20 * GIB), (root / "venv", 10 * GIB)])
            self.assertFalse((root / "cache").exists())


class AtomicOutputTests(unittest.TestCase):
    def test_encoder_failure_preserves_previous_result_and_removes_partial(self):
        def fail_encode(*args, output_path, **kwargs):
            Path(output_path).write_bytes(b"partial")
            raise RuntimeError("codec failed")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.mp4"
            output.write_bytes(b"previous valid result")
            with self.assertRaisesRegex(RuntimeError, "codec failed"):
                write_verified_video(fail_encode, None, None, 32000, output, width=32, height=32, frames=24)
            self.assertEqual(output.read_bytes(), b"previous valid result")
            self.assertEqual(list(output.parent.iterdir()), [output])

    def test_validation_failure_preserves_previous_result(self):
        def encode(*args, output_path, **kwargs):
            Path(output_path).write_bytes(b"invalid media")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.mp4"
            output.write_bytes(b"previous")
            with patch("verify_media.verify_media", side_effect=RuntimeError("missing audio")):
                with self.assertRaisesRegex(RuntimeError, "missing audio"):
                    write_verified_video(encode, None, None, 32000, output, width=32, height=32, frames=24)
            self.assertEqual(output.read_bytes(), b"previous")
            self.assertEqual(list(output.parent.iterdir()), [output])


if __name__ == "__main__":
    unittest.main()
