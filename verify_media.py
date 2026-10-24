"""Decode a generated MP4 and check dimensions, frame count, stereo audio and duration."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path


def verify_media(path: Path, *, width: int, height: int, frames: int, fps: int = 24) -> None:
    import av
    import numpy as np

    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing or empty MP4: {path}")
    with av.open(str(path)) as container:
        if len(container.streams.video) != 1 or len(container.streams.audio) != 1:
            raise RuntimeError("MP4 must contain exactly one video and one audio stream")
        video, audio = container.streams.video[0], container.streams.audio[0]
        if video.codec_context.name != "h264" or audio.codec_context.name != "aac":
            raise RuntimeError("Expected H.264 video and AAC audio")
        if (video.width, video.height) != (width, height):
            raise RuntimeError(f"Unexpected video dimensions: {video.width}x{video.height}")
        if video.average_rate != Fraction(fps):
            raise RuntimeError(f"Unexpected frame rate: {video.average_rate}")
        if audio.sample_rate != 32000 or len(audio.layout.channels) != 2:
            raise RuntimeError("Expected 32000 Hz stereo audio")
        decoded = sum(1 for _ in container.decode(video=0))
        if decoded != frames:
            raise RuntimeError(f"Truncated/unexpected video: decoded {decoded} frames, expected {frames}")
    # Reopen to decode the audio from its beginning after the video pass reaches EOF.
    samples = 0
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            if not np.isfinite(frame.to_ndarray()).all():
                raise RuntimeError("Non-finite decoded audio")
            samples += frame.samples
    if samples == 0 or abs(samples / 32000 - frames / fps) > 0.15:
        raise RuntimeError(f"Audio/video duration mismatch: {samples/32000:.3f}s vs {frames/fps:.3f}s")


def write_verified_video(encode, video, audio, sampling_rate, output: Path,
                         *, width: int, height: int, frames: int) -> None:
    """Publish only a fully encoded/validated file; preserve any prior output on failure."""
    import os
    import tempfile

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".h3-", suffix=".mp4", dir=output.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        encode(video, fps=24, output_path=str(temporary), audio=audio,
               audio_sample_rate=sampling_rate)
        verify_media(temporary, width=width, height=height, frames=frames)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
