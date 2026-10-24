"""Read-only hardware checks; uses only the Python standard library."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess

from h3_config import GIB


def existing_parent(path: Path) -> Path:
    path = path.expanduser().resolve()
    while not path.exists():
        path = path.parent
    if not path.is_dir():
        raise RuntimeError(f"Expected a directory: {path}")
    return path


def cgroup_remaining(root: Path = Path("/sys/fs/cgroup"), membership: Path = Path("/proc/self/cgroup")) -> list[int]:
    """Include ancestor limits and both cgroup v1/v2; ignore unlimited values."""
    candidates = [(root, "memory.max", "memory.current"),
                  (root / "memory", "memory.limit_in_bytes", "memory.usage_in_bytes")]
    if membership.exists():
        for line in membership.read_text().splitlines():
            _, controllers, relative = line.split(":", 2)
            if controllers == "":
                base, limit, usage = root, "memory.max", "memory.current"
            elif "memory" in controllers.split(","):
                base, limit, usage = root / "memory", "memory.limit_in_bytes", "memory.usage_in_bytes"
            else:
                continue
            child = (base / relative.lstrip("/")).resolve()
            base = base.resolve()
            while child.is_relative_to(base):
                candidates.append((child, limit, usage))
                if child == base:
                    break
                child = child.parent
    remaining = []
    for directory, limit_name, usage_name in candidates:
        limit_path, usage_path = directory / limit_name, directory / usage_name
        if not limit_path.exists() or not usage_path.exists():
            continue
        limit = limit_path.read_text().strip()
        if limit != "max":
            remaining.append(max(0, int(limit) - int(usage_path.read_text().strip())))
    return remaining


def available_memory(meminfo: Path = Path("/proc/meminfo")) -> int:
    data = {line.split(":", 1)[0]: int(line.split()[1]) * 1024
            for line in meminfo.read_text().splitlines()}
    return min([data["MemAvailable"], *cgroup_remaining()])


def check_disks(budgets: list[tuple[Path, int]]) -> None:
    devices: dict[int, tuple[Path, int]] = {}
    for path, required in budgets:
        parent = existing_parent(path)
        if not os.access(parent, os.W_OK | os.X_OK):
            raise RuntimeError(f"Directory is not writable/searchable: {parent}")
        device = parent.stat().st_dev
        previous = devices.get(device, (parent, 0))[1]
        devices[device] = (parent, previous + required)
    for path, required in devices.values():
        free = shutil.disk_usage(path).free
        if free < required:
            raise RuntimeError(f"Disk at {path}: {free/GIB:.1f} GiB free; need {required/GIB:.1f} GiB working space")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--pip-cache", type=Path, required=True)
    parser.add_argument("--install", action="store_true", help="Reserve additional space for Python/CUDA installation")
    args = parser.parse_args()
    result = subprocess.run(
        ["nvidia-smi", "-i", args.gpu, "--query-gpu=memory.total,memory.free,driver_version",
         "--format=csv,noheader,nounits"], check=True, capture_output=True, text=True,
    )
    rows = result.stdout.strip().splitlines()
    if len(rows) != 1:
        raise RuntimeError("Expected one GPU; select a full GPU UUID")
    total, free, driver = [x.strip() for x in rows[0].split(",")]
    if int(total) < 75000 or int(free) < 75000:
        raise RuntimeError(f"BF16 profile needs 75000 MiB total AND free VRAM; found {total}/{free}. Free other jobs or use a separately configured quantized profile")
    # 525.60.13 is the CUDA 12.x minor-compatibility floor, not a guarantee for every kernel.
    if tuple(map(int, driver.split("."))) < (525, 60, 13):
        raise RuntimeError(f"Driver {driver} is below the CUDA 12.x compatibility floor 525.60.13")
    if tuple(map(int, driver.split("."))) < (570, 26):
        print(f"WARNING: driver {driver}; prefer 570.26+ for CUDA 12.8. Runtime kernels will be tested.")
    memory = available_memory()
    if memory < 150 * GIB:
        raise RuntimeError(f"Need 150 GiB available host/container RAM; found {memory/GIB:.1f} GiB (swap is not counted)")
    budgets = [(args.cache, 20 * GIB), (args.output.parent, 2 * GIB),
               (args.environment, (20 if args.install else 1) * GIB)]
    if args.install:
        budgets.append((args.pip_cache, 10 * GIB))
    check_disks(budgets)
    print(f"Hardware OK: {args.gpu}, VRAM {free}/{total} MiB, driver {driver}, available RAM {memory/GIB:.1f} GiB")
    print("Model space is checked separately against missing files at the pinned revision before download.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Preflight failed: {exc}") from exc
