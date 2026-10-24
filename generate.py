"""MiniMax-H3 t2va smoke generation using the official Diffusers ModularPipeline."""

from __future__ import annotations

import argparse
from pathlib import Path


MODEL_ID = "MiniMaxAI/MiniMax-H3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MiniMax-H3 video with audio")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=544)
    parser.add_argument("--frames", type=int, default=124)
    parser.add_argument("--steps", type=int, default=9)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.width <= 0 or args.height <= 0 or args.width % 32 or args.height % 32:
        parser.error("width and height must be positive multiples of 32")
    if args.frames != 17 * ((args.frames - 5 + 16) // 17) + 5 or not 120 <= args.frames <= 360:
        parser.error("frames must be 17*n+5 and represent 5–15 seconds at 24 fps")
    if args.steps < 2:
        parser.error("steps must be at least 2")
    return args


def main() -> None:
    args = parse_args()

    import torch
    from diffusers import ComponentsManager, ModularPipeline
    from diffusers.utils.export_utils import encode_video

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch cannot access an NVIDIA GPU; check the driver and CUDA wheel")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("The selected GPU does not support BF16")

    # Only load the t2va transformer partition. The manager swaps components
    # between host memory and the selected GPU as the workflow advances.
    manager = ComponentsManager()
    pipe = ModularPipeline.from_pretrained(
        MODEL_ID, workflow="t2va", components_manager=manager
    )
    pipe.load_components(dtype=torch.bfloat16)
    manager.enable_auto_cpu_offload(device="cuda", memory_reserve_margin="12GB")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with torch.inference_mode():
        result = pipe(
            prompt=args.prompt,
            num_frames=args.frames,
            width=args.width,
            height=args.height,
            num_inference_steps=args.steps,
            generator=torch.Generator(device="cpu").manual_seed(args.seed),
            output=["videos", "audio", "sampling_rate"],
        )

    encode_video(
        result["videos"][0],
        fps=24,
        output_path=str(args.output),
        audio=result["audio"][0],
        audio_sample_rate=result["sampling_rate"],
    )
    if not args.output.is_file() or args.output.stat().st_size == 0:
        raise RuntimeError(f"MP4 was not written: {args.output}")
    print(f"Generated: {args.output}")


if __name__ == "__main__":
    main()
