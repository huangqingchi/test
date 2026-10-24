"""Cheap import, GPU-kernel and media-encoding checks before downloading the model."""

from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path
import tempfile


def check_gpu() -> None:
    import torch
    from torch.nn.functional import scaled_dot_product_attention

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("Exactly one CUDA GPU must be visible; check driver and H3_GPU_INDEX")
    if torch.version.cuda != "12.8":
        raise RuntimeError(f"Expected CUDA 12.8 wheel, found {torch.version.cuda}")
    if not torch.cuda.is_bf16_supported(including_emulation=False):
        raise RuntimeError("The selected GPU does not support native BF16")
    # is_available() alone does not detect missing kernels / broken CUDA libraries.
    x = torch.ones((32, 32), device="cuda", dtype=torch.bfloat16)
    if not torch.isfinite(x @ x).all().item():
        raise RuntimeError("BF16 matrix multiplication failed")
    q = torch.randn((1, 2, 32, 64), device="cuda", dtype=torch.bfloat16)
    if not torch.isfinite(scaled_dot_product_attention(q, q, q)).all().item():
        raise RuntimeError("CUDA attention test failed")
    torch.cuda.synchronize()
    print(f"CUDA kernels OK: {torch.cuda.get_device_name(0)}; torch {torch.__version__}")


def check_imports_and_media() -> None:
    import numpy as np
    import torch
    import torchvision
    from diffusers import ComponentsManager, ModularPipeline
    from diffusers.modular_pipelines.minimax_h3 import MiniMaxH3Blocks
    from diffusers.utils.export_utils import encode_video
    from transformers import Qwen3VLForConditionalGeneration, Qwen3VLProcessor

    from verify_media import verify_media

    # Force lazy class imports and instantiate only blocks, never weights.
    assert ComponentsManager and ModularPipeline and Qwen3VLForConditionalGeneration and Qwen3VLProcessor
    MiniMaxH3Blocks()
    torchvision.ops.nms(torch.tensor([[0., 0., 2., 2.]]), torch.tensor([1.]), 0.5)
    for name in ("torch", "torchvision", "diffusers", "transformers", "huggingface_hub", "av"):
        print(f"{name}=={importlib.metadata.version(name)}")
    with tempfile.TemporaryDirectory(prefix="h3-codec-") as directory:
        path = Path(directory) / "codec-test.mp4"
        video = np.zeros((24, 32, 32, 3), dtype=np.float32)
        audio = torch.zeros((2, 32000), dtype=torch.float32)
        encode_video(video, fps=24, output_path=str(path), audio=audio, audio_sample_rate=32000)
        verify_media(path, width=32, height=32, frames=24)
    print("H3 imports, torchvision native ops, H.264/AAC encoding and full decoding passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu", action="store_true", help="Only test imports/media; NOT GPU deployment acceptance")
    args = parser.parse_args()
    if not args.cpu:
        check_gpu()
    check_imports_and_media()
