"""Actual pinned-library/media integration; no GPU and no model tensors loaded."""

import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

from generate import parse_args
from h3_config import COMPONENTS, ROOT_CONFIGS, WEIGHT_COMPONENTS
from smoke_fixtures import create_fixtures
from verify_model import verify_workflow_indexes
from workflow_inputs import load_inputs, media_duration


@unittest.skipUnless(importlib.util.find_spec("diffusers"), "Requires the installed CPU integration environment")
class ActualWorkflowIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.media = create_fixtures(cls.root / "media")

    def test_all_workflow_indexes_route_to_local_correct_weights(self):
        root = self.root / "model-layout"
        root.mkdir()
        for name in ROOT_CONFIGS:
            shutil.copy(Path(__file__).parent / "fixtures" / name, root / name)
        for component in COMPONENTS:
            folder = root / component
            folder.mkdir()
            if component in WEIGHT_COMPONENTS:
                # Deliberately empty filename fixtures. No fake model is loaded or inferred.
                (folder / "model.safetensors").touch()
            elif "scheduler" in component:
                (folder / "scheduler_config.json").write_text("{}")
            else:
                (folder / "tokenizer_config.json").write_text("{}")
        routes = verify_workflow_indexes(root)
        self.assertIn("transformer_ref", routes["ref2va"])
        self.assertNotIn("transformer", routes["ref2va"])
        for workflow in ("t2va", "fl2va"):
            self.assertIn("transformer", routes[workflow])
            self.assertNotIn("transformer_ref", routes[workflow])

    def args(self, *flags):
        return parse_args(["--prompt", "red ball", "--output", str(self.root / "out.mp4"), *map(str, flags)])

    def test_first_last_and_both_frames_decode(self):
        for names in [("image",), ("last-image",), ("image", "last-image")]:
            flags = [part for name in names for part in ("--" + name, self.media["first"])]
            result = load_inputs(self.args("--workflow", "fl2va", *flags))
            self.assertEqual(set(result), {name.replace("-", "_") for name in names})
            self.assertTrue(all(image.mode == "RGB" for image in result.values()))

    def test_real_reference_decoder_preserves_modality_order_and_rates(self):
        args = self.args("--workflow", "ref2va", "--reference", "video", self.media["video"],
                         "--reference", "image", self.media["first"],
                         "--reference", "audio", self.media["audio"])
        refs = load_inputs(args)["references"]
        self.assertEqual([r.kind for r in refs], ["video", "image", "audio"])
        self.assertEqual(refs[0].fps, 24)
        self.assertEqual(len(refs[0].frames), 48)
        self.assertIsNotNone(refs[0].audio)
        self.assertEqual(refs[2].sample_rate, 32000)
        self.assertEqual(refs[2].audio.shape[-1], 64000)

    def test_corrupt_reference_rejected_before_weight_loading(self):
        path = self.root / "bad.mp4"
        path.write_bytes(b"not a video")
        with self.assertRaises(Exception):
            load_inputs(self.args("--workflow", "ref2va", "--reference", "video", path))

    def test_no_requested_stream_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no video stream"):
            media_duration(self.media["audio"], "video")

    def test_short_and_long_audio_references_rejected(self):
        import wave

        for seconds in (1, 16):
            path = self.root / f"audio-{seconds}.wav"
            with wave.open(str(path), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(8000)
                stream.writeframes(b"\0\0" * (8000 * seconds))
            with self.assertRaisesRegex(ValueError, "seconds"):
                media_duration(path, "audio")


if __name__ == "__main__":
    unittest.main()
