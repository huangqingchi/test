"""Local media inputs for all three MiniMax-H3 workflows; validate before loading weights."""

from __future__ import annotations

from collections import Counter
import math
from pathlib import Path


def validate_request(workflow: str, image: Path | None, last_image: Path | None,
                     references: list[tuple[str, Path]]) -> None:
    if workflow == "t2va" and (image or last_image or references):
        raise ValueError("t2va accepts text only; select fl2va for keyframes or ref2va for references")
    if workflow == "fl2va":
        if not (image or last_image):
            raise ValueError("fl2va requires --image and/or --last-image")
        if references:
            raise ValueError("fl2va cannot use --reference; choose ref2va")
    if workflow == "ref2va":
        if image or last_image:
            raise ValueError("ref2va uses --reference, not --image/--last-image")
        if not references:
            raise ValueError("ref2va requires at least one --reference")
        counts = Counter(kind for kind, _ in references)
        if any(kind not in ("image", "video", "audio") for kind in counts):
            raise ValueError("Reference kind must be image, video or audio")
        if len(references) > 12 or any(counts[kind] > limit for kind, limit in
                                        (("image", 9), ("video", 3), ("audio", 3))):
            raise ValueError("H3 supports at most 9 image, 3 video, 3 audio and 12 total references")
        if not counts["image"] and not counts["video"]:
            raise ValueError("Audio references need at least one image or video reference")
    paths = [path for path in (image, last_image) if path] + [path for _, path in references]
    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Input must be a nonempty local file: {path}")


def read_image(path: Path, *, reference: bool = False):
    from PIL import Image, ImageOps

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.load()
    if reference and not 0.25 <= image.width / image.height <= 4:
        raise ValueError(f"Reference image aspect ratio must be 1:4 to 4:1: {path}")
    return image


def media_duration(path: Path, kind: str) -> float:
    """Decode once with bounded duration validation, before the upstream in-memory decoder."""
    import av

    with av.open(str(path)) as container:
        streams = container.streams.video if kind == "video" else container.streams.audio
        if not streams:
            raise ValueError(f"Reference has no {kind} stream: {path}")
        stream = streams[0]
        if kind == "video":
            rate = float(stream.average_rate or 0)
        else:
            rate = stream.sample_rate
            if len(stream.layout.channels) not in (1, 2):
                raise ValueError(f"Reference audio must be mono or stereo: {path}")
        if not rate or not math.isfinite(rate) or rate <= 0:
            raise ValueError(f"Reference has no valid {kind} rate: {path}")
        units = 0
        for frame in container.decode(stream):
            units += 1 if kind == "video" else frame.samples
            if units / rate > 15.05:  # AAC padding can add a fraction of a frame.
                raise ValueError(f"Reference {kind} exceeds 15 seconds: {path}")
        duration = units / rate
        if not 2 - 1e-6 <= duration <= 15.05:
            raise ValueError(f"Reference {kind} must last 2–15 seconds: {path} ({duration:.3f}s)")
        return duration


def load_inputs(args) -> dict:
    # All paths were resolved/validated at CLI parsing; no URL fetching is supported.
    if args.workflow == "t2va":
        return {}
    if args.workflow == "fl2va":
        return {name: read_image(path) for name, path in
                (("image", args.image), ("last_image", args.last_image)) if path is not None}

    from diffusers.modular_pipelines.minimax_h3 import (
        MiniMaxH3AudioReference, MiniMaxH3ImageReference, MiniMaxH3VideoReference,
    )

    durations = Counter()
    # Validate all clips before holding the full collection in memory.
    for kind, path in args.reference:
        if kind in ("video", "audio"):
            durations[kind] += media_duration(path, kind)
    if any(value > 15.05 for value in durations.values()):
        raise ValueError("Total reference video duration and total reference audio duration must each be <=15s")
    references = []
    for kind, path in args.reference:
        if kind == "image":
            reference = MiniMaxH3ImageReference(image=read_image(path, reference=True))
        elif kind == "video":
            reference = MiniMaxH3VideoReference.from_file(str(path))
        else:
            reference = MiniMaxH3AudioReference.from_file(str(path))
        references.append(reference)  # Preserve the user's cross-modality order.
    return {"references": references}
