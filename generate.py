"""MiniMax-H3 t2va smoke generation using the official Diffusers ModularPipeline."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from download_model import local_snapshot
from h3_config import MODEL_REVISION
from verify_media import write_verified_video

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MiniMax-H3 video with audio")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=544)
    parser.add_argument("--frames", type=int, default=124)
    parser.add_argument("--steps", type=int, default=9)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    args.output = args.output.expanduser().resolve()
    if not args.prompt.strip():
        parser.error("prompt must not be empty")
    if args.output.suffix.lower() != ".mp4":
        parser.error("output must have an .mp4 extension")
    if args.width <= 0 or args.height <= 0 or args.width % 32 or args.height % 32:
        parser.error("width and height must be positive multiples of 32")
    if (args.frames - 5) % 17 or not 120 <= args.frames <= 360:
        parser.error("frames must be 17*n+5 and represent 5–15 seconds at 24 fps")
    if args.steps < 2:
        parser.error("steps must be at least 2")
    if not 0 <= args.seed < 2**63:
        parser.error("seed must be between 0 and 2**63-1")
    return args


def main() -> None:
    args = parse_args()
    # Check the cache before importing libraries that could otherwise initiate downloads.
    snapshot = local_snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and not args.output.is_file():
        raise RuntimeError(f"Output is not a file: {args.output}")
    if not os.access(args.output.parent, os.W_OK):
        raise RuntimeError(f"Output directory is not writable: {args.output.parent}")

    import numpy as np
    import torch
    from diffusers import ComponentsManager, ModularPipeline
    from diffusers.utils.export_utils import encode_video

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch cannot access an NVIDIA GPU; check the driver and CUDA wheel")
    if not torch.cuda.is_bf16_supported(including_emulation=False):
        raise RuntimeError("The selected GPU does not support BF16")

    # Only load the t2va transformer partition. The manager swaps components
    # between host memory and the selected GPU as the workflow advances.
    manager = ComponentsManager()
    pipe = ModularPipeline.from_pretrained(
        str(snapshot), workflow="t2va", components_manager=manager, local_files_only=True
    )
    # Override every component source explicitly: the repository indexes contain
    # remote model IDs with revision=null, even when the pipeline index is local.
    pipe.load_components(dtype=torch.bfloat16, local_files_only=True,
                         pretrained_model_name_or_path=str(snapshot), revision=None)
    manager.enable_auto_cpu_offload(device="cuda", memory_reserve_margin="12GB")

    print(f"Generating {args.width}x{args.height}, {args.frames} frames, grid points={args.steps}, seed={args.seed}, model={MODEL_REVISION}")
    with torch.inference_mode():
        result = pipe(
            prompt=args.prompt,
            num_frames=args.frames,
            width=args.width,
            height=args.height,
            num_inference_steps=args.steps,
            generator=torch.Generator(device="cpu").manual_seed(args.seed),
            output_type="np",
            output=["videos", "audio", "sampling_rate"],
        )

    video = result["videos"][0]
    audio = result["audio"][0].float().cpu()
    if not np.isfinite(video).all() or not torch.isfinite(audio).all().item():
        raise RuntimeError("Model generated non-finite video/audio values")
    write_verified_video(
        encode_video, video, audio, result["sampling_rate"], args.output,
        width=args.width, height=args.height, frames=args.frames,
    )
    print(f"Generated and decoded successfully: {args.output}")


if __name__ == "__main__":
    main()
