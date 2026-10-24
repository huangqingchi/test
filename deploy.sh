#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
H3_GPU_INDEX="${H3_GPU_INDEX:-0}"
H3_HF_HOME="${H3_HF_HOME:-${PROJECT_DIR}/.cache/huggingface}"
H3_OUTPUT="${H3_OUTPUT:-${PROJECT_DIR}/outputs/smoke-test.mp4}"
H3_PROMPT="${H3_PROMPT:-A red fox walks through a snowy pine forest, with wind and footsteps audible.}"
H3_DIFFUSERS_REF="${H3_DIFFUSERS_REF:-main}"
export HF_HOME="${H3_HF_HOME}"
export CUDA_VISIBLE_DEVICES="${H3_GPU_INDEX}"

MODE="${1:-all}"
case "${MODE}" in
  all|--preflight|--setup|--test) ;;
  *) echo "Usage: bash deploy.sh [--preflight|--setup|--test]" >&2; exit 2 ;;
esac

fail() { echo "ERROR: $*" >&2; exit 1; }

install_system_packages() {
  local packages=()
  command -v python3 >/dev/null || packages+=(python3)
  command -v git >/dev/null || packages+=(git)
  command -v ffprobe >/dev/null || packages+=(ffmpeg)
  if [[ "$(dpkg-query -W -f='${Status}' python3-venv 2>/dev/null || true)" != "install ok installed" ]]; then
    packages+=(python3-venv)
  fi
  if ((${#packages[@]})); then
    if ((EUID == 0)); then
      apt-get update
      apt-get install -y "${packages[@]}"
    else
      command -v sudo >/dev/null || fail "sudo is required to install: ${packages[*]}"
      sudo apt-get update
      sudo apt-get install -y "${packages[@]}"
    fi
  fi
}

preflight() {
  [[ -r /etc/os-release ]] || fail "This script requires Ubuntu"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == ubuntu ]] || fail "This script supports Ubuntu only"
  [[ "$(uname -m)" == x86_64 ]] || fail "This plan targets x86_64"
  command -v python3 >/dev/null || fail "python3 missing"
  command -v git >/dev/null || fail "git missing"
  command -v ffprobe >/dev/null || fail "ffprobe missing"
  command -v nvidia-smi >/dev/null || fail "NVIDIA driver / nvidia-smi missing"
  python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
  python3 -m venv --help >/dev/null 2>&1 || fail "python3-venv missing"

  local vram_mib ram_kib free_gib required_gib
  vram_mib="$(nvidia-smi -i "${H3_GPU_INDEX}" --query-gpu=memory.total --format=csv,noheader,nounits | head -n 1 | tr -d '[:space:]')"
  [[ "${vram_mib}" =~ ^[0-9]+$ ]] || fail "Cannot read GPU ${H3_GPU_INDEX} memory"
  ((vram_mib >= 75000)) || fail "GPU ${H3_GPU_INDEX} has ${vram_mib} MiB; this BF16 profile needs an 80GB-class GPU"
  ram_kib="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
  ((ram_kib >= 150 * 1024 * 1024)) || fail "This BF16 profile needs at least 150 GiB system RAM"
  mkdir -p -- "${HF_HOME}"
  free_gib="$(df -BG --output=avail "${HF_HOME}" | tail -n 1 | tr -dc '0-9')"
  # A cached snapshot needs only working space on later runs.
  if [[ -d "${HF_HOME}/hub/models--MiniMaxAI--MiniMax-H3/snapshots" ]]; then
    required_gib=20
  else
    required_gib=180
  fi
  [[ -n "${free_gib}" ]] || fail "Cannot read available cache disk space"
  ((free_gib >= required_gib)) || fail "Cache disk has ${free_gib} GiB free; need ${required_gib} GiB"
  echo "Preflight OK: GPU ${H3_GPU_INDEX}, ${vram_mib} MiB VRAM; cache ${free_gib} GiB free"
}

setup_env() {
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
  "${VENV_DIR}/bin/python" -m pip install "git+https://github.com/huggingface/diffusers.git@${H3_DIFFUSERS_REF}"
  "${VENV_DIR}/bin/python" -m pip install -r "${PROJECT_DIR}/requirements.txt"
  "${VENV_DIR}/bin/python" -c 'import torch; from diffusers import ComponentsManager, ModularPipeline; assert torch.cuda.is_available(), "CUDA unavailable"; assert torch.cuda.is_bf16_supported(), "BF16 unavailable"'
  echo "Python environment ready"
}

test_generation() {
  [[ -x "${VENV_DIR}/bin/python" ]] || fail "Virtual environment missing; run bash deploy.sh --setup"
  "${VENV_DIR}/bin/python" "${PROJECT_DIR}/generate.py" \
    --prompt "${H3_PROMPT}" --output "${H3_OUTPUT}" \
    --width 960 --height 544 --frames 124 --steps 9
  [[ -s "${H3_OUTPUT}" ]] || fail "Output MP4 missing or empty"
  [[ -n "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 "${H3_OUTPUT}")" ]] || fail "MP4 has no video stream"
  [[ -n "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 "${H3_OUTPUT}")" ]] || fail "MP4 has no audio stream"
  echo "Smoke test passed: ${H3_OUTPUT}"
}

case "${MODE}" in
  --preflight) preflight ;;
  --setup) install_system_packages; preflight; setup_env ;;
  --test) preflight; test_generation ;;
  all) install_system_packages; preflight; setup_env; test_generation ;;
esac
