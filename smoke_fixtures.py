"""Small deterministic diagnostic media; no external files or generation service needed."""

from pathlib import Path
import wave


def create_fixtures(directory: Path) -> dict[str, Path]:
    import numpy as np
    import torch
    from PIL import Image, ImageDraw
    from diffusers.utils.export_utils import encode_video

    directory.mkdir(parents=True, exist_ok=True)
    paths = {name: directory / filename for name, filename in (
        ("first", "first.png"), ("last", "last.png"),
        ("video", "motion.mp4"), ("audio", "tone.wav"),
    )}
    images = []
    for index in range(48):
        image = Image.new("RGB", (320, 256), (220, 230, 240))
        draw = ImageDraw.Draw(image)
        x = 32 + index * 4
        draw.ellipse((x, 100, x + 48, 148), fill=(210, 40, 40))
        images.append(image)
    images[0].save(paths["first"])
    images[-1].save(paths["last"])
    # Exactly 2 seconds at H3's native rates; mixed ref2va exercises all media decoders.
    samples = 0.04 * np.sin(2 * np.pi * 440 * np.arange(64000) / 32000)
    pcm = (samples * 32767).astype("<i2")
    with wave.open(str(paths["audio"]), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(32000)
        stream.writeframes(pcm.tobytes())
    audio = torch.from_numpy(np.stack([samples, samples]).astype(np.float32))
    encode_video(images, fps=24, output_path=str(paths["video"]), audio=audio, audio_sample_rate=32000)
    return paths
