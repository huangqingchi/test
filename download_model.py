"""Download the complete pinned H3 Diffusers model, including both transformer partitions."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from h3_config import (COMPONENTS, GIB, MANIFEST_SCHEMA, MODEL_ID, MODEL_PROFILE,
                       MODEL_REVISION, ROOT_CONFIGS, WEIGHT_COMPONENTS)


def selected_file(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        return False
    return name in ROOT_CONFIGS or (len(path.parts) > 1 and path.parts[0] in COMPONENTS)


def validate_manifest(files: dict[str, int]) -> None:
    if not files or any(not selected_file(name) or not isinstance(size, int) or size <= 0
                        for name, size in files.items()):
        raise RuntimeError("Invalid model file manifest")
    if not all(name in files for name in ROOT_CONFIGS):
        raise RuntimeError("Missing pipeline indexes in model manifest")
    for component in COMPONENTS:
        if not any(name.startswith(component + "/") for name in files):
            raise RuntimeError(f"Missing component in manifest: {component}")
    for component in WEIGHT_COMPONENTS:
        if not any(name.startswith(component + "/") and name.endswith(".safetensors") for name in files):
            raise RuntimeError(f"Missing weights in manifest: {component}")


def missing_files(snapshot: Path, files: dict[str, int]) -> dict[str, int]:
    return {name: size for name, size in files.items()
            if not (snapshot / name).is_file() or (snapshot / name).stat().st_size != size}


def cache_paths() -> tuple[Path, Path]:
    # Match huggingface_hub's HF_HOME / HF_HUB_CACHE / XDG_CACHE_HOME defaults.
    from huggingface_hub.constants import HF_HUB_CACHE

    cache = Path(HF_HUB_CACHE)
    repo = cache / ("models--" + MODEL_ID.replace("/", "--"))
    return repo / "snapshots" / MODEL_REVISION, repo / f"{MODEL_PROFILE}-{MODEL_REVISION}.json"


def local_snapshot() -> Path:
    snapshot, manifest = cache_paths()
    if not manifest.is_file():
        raise RuntimeError("Verified model manifest missing; run bash deploy.sh --download")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("repo_id") != MODEL_ID or data.get("revision") != MODEL_REVISION:
        raise RuntimeError("Cached manifest belongs to another model revision")
    if data.get("schema") != MANIFEST_SCHEMA or data.get("profile") != MODEL_PROFILE:
        raise RuntimeError("Full H3 manifest required; rerun --download to upgrade the partial cache")
    files = data["files"]
    validate_manifest(files)
    missing = missing_files(snapshot, files)
    if missing:
        raise RuntimeError(f"Model cache is incomplete ({len(missing)} files); rerun bash deploy.sh --download")
    return snapshot.resolve()


def download() -> Path:
    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.constants import HF_HUB_CACHE

    # Metadata fetch also tests network/access without loading any model weights.
    info = HfApi().model_info(MODEL_ID, revision=MODEL_REVISION, files_metadata=True)
    if info.sha != MODEL_REVISION:
        raise RuntimeError("Hub did not resolve the pinned model revision")
    files = {item.rfilename: item.size for item in info.siblings if selected_file(item.rfilename)}
    validate_manifest(files)
    snapshot, manifest = cache_paths()
    missing = missing_files(snapshot, files)
    cache = Path(HF_HUB_CACHE)
    cache.mkdir(parents=True, exist_ok=True)
    # Conservatively budget the full size of incomplete files; never trust a .incomplete blob.
    required = sum(missing.values()) + 20 * GIB
    free = shutil.disk_usage(cache).free
    print(f"Full MiniMax-H3 (t2va/fl2va/ref2va): {sum(files.values())/GIB:.2f} GiB; missing/incomplete: {sum(missing.values())/GIB:.2f} GiB; free: {free/GIB:.2f} GiB")
    if free < required:
        raise RuntimeError(f"Cache needs {required/GIB:.2f} GiB free including reserve; choose H3_HF_HOME on a larger disk")
    # Sequential large-file downloads limit peak temporary space. Hub resumes interrupted blobs.
    for index, name in enumerate(missing, 1):
        print(f"Downloading {index}/{len(missing)}: {name}", flush=True)
        path = snapshot / name
        # Force only a corrupt completed file, otherwise preserve normal resume/cache behavior.
        hf_hub_download(MODEL_ID, name, revision=MODEL_REVISION,
                        force_download=path.is_file() and path.stat().st_size != files[name])
    if missing_files(snapshot, files):
        raise RuntimeError("Model download incomplete; rerun --download to resume")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    data = {"repo_id": MODEL_ID, "revision": MODEL_REVISION, "files": files,
            "schema": MANIFEST_SCHEMA, "profile": MODEL_PROFILE}
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=manifest.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, indent=2)
    try:
        os.replace(temporary, manifest)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Verified snapshot: {snapshot}")
    return snapshot.resolve()


if __name__ == "__main__":
    download()
