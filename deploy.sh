#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "${PROJECT_DIR}"
MODE="${1:-all}"
fail() { echo "ERROR: $*" >&2; exit 1; }
usage() { echo "Usage: bash deploy.sh [--preflight|--setup|--download|--test|--help]"; }
[[ $# -le 1 ]] || { usage; exit 2; }
case "${MODE}" in
  all|--preflight|--setup|--download|--test) ;;
  --help|-h) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac
report_failure() {
  local status="$1" line="$2"
  echo "ERROR: stage=${STAGE:-bootstrap}, line=${line}, exit=${status}. See README.md troubleshooting." >&2
  exit "${status}"
}
trap 'report_failure "$?" "$LINENO"' ERR

# Validate the platform before any package-manager or filesystem mutation.
STAGE=platform
[[ -r /etc/os-release ]] || fail "Ubuntu x86_64 is required"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == ubuntu && "$(uname -m)" == x86_64 ]] || fail "Ubuntu x86_64 is required"
H3_PYTHON="${H3_PYTHON:-python3}"
command -v "${H3_PYTHON}" >/dev/null || fail "Install Python 3.11–3.13; Ubuntu 24.04 supplies Python 3.12"
"${H3_PYTHON}" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else "Python 3.11–3.13 required; set H3_PYTHON to a supported interpreter")'
VENV_DIR="${PROJECT_DIR}/.venv"
PYTHON="${VENV_DIR}/bin/python"
export HF_HOME="${H3_HF_HOME:-${HF_HOME:-${PROJECT_DIR}/.cache/huggingface}}"
export HF_HUB_CACHE="${HF_HOME}/hub"
export PIP_CACHE_DIR="${H3_PIP_CACHE:-${PROJECT_DIR}/.cache/pip}"
export PYTHONUNBUFFERED=1
export PYTHONNOUSERSITE=1
# A UUID avoids differences between nvidia-smi and CUDA device enumeration order.
if [[ -n "${H3_GPU_INDEX:-}" ]]; then
  GPU_SELECTOR="${H3_GPU_INDEX}"
elif [[ -n "${CUDA_VISIBLE_DEVICES+x}" ]]; then
  GPU_SELECTOR="${CUDA_VISIBLE_DEVICES}"
else
  GPU_SELECTOR=0
fi
[[ -n "${GPU_SELECTOR}" && "${GPU_SELECTOR}" != *,* && "${GPU_SELECTOR}" != -1 ]] || fail "Select exactly one full GPU with H3_GPU_INDEX (index or GPU UUID)"
command -v nvidia-smi >/dev/null || fail "NVIDIA driver / nvidia-smi missing; install the host driver first"
GPU_UUID="$(nvidia-smi -i "${GPU_SELECTOR}" --query-gpu=uuid --format=csv,noheader)"
[[ "${GPU_UUID}" == GPU-* && "${GPU_UUID}" != *$'\n'* ]] || fail "A single full GPU is required; MIG is not supported by this profile"
export CUDA_VISIBLE_DEVICES="${GPU_UUID}"
H3_OUTPUT="${H3_OUTPUT:-${PROJECT_DIR}/outputs/smoke-test.mp4}"
H3_PROMPT="${H3_PROMPT:-A red fox walks through a snowy pine forest, with wind and footsteps audible.}"

STAGE=hardware
PREFLIGHT_FLAGS=()
if [[ "${MODE}" == all || "${MODE}" == --setup || "${MODE}" == --preflight ]]; then
  PREFLIGHT_FLAGS+=(--install)
fi
"${H3_PYTHON}" preflight.py --gpu "${GPU_UUID}" --cache "${HF_HUB_CACHE}" --output "${H3_OUTPUT}" --environment "${PROJECT_DIR}" --pip-cache "${PIP_CACHE_DIR}" "${PREFLIGHT_FLAGS[@]}"
if [[ "${MODE}" == --preflight ]]; then
  echo "Hardware preflight passed. Dependencies, model access and GPU kernels have not been tested."
  exit 0
fi

# Serialize setup/download/generation within this checkout.
command -v flock >/dev/null || fail "flock missing; install util-linux"
exec 9>"${PROJECT_DIR}/.cache-deploy.lock"
flock -n 9 || fail "Another deployment/generation is running in this checkout"
mkdir -p logs
LOG_FILE="${PROJECT_DIR}/logs/deploy-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
exec > >(tee -a "${LOG_FILE}") 2>&1
# Route pip's temporary downloads to a checked filesystem, not a small /tmp mount.
export TMPDIR="${PROJECT_DIR}/.cache/tmp"
mkdir -p "${TMPDIR}"
echo "Deployment log: ${LOG_FILE}"

install_system_packages() {
  local packages=() apt_prefix=()
  command -v git >/dev/null || packages+=(git)
  if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then packages+=(ffmpeg); fi
  # venv --help does not check ensurepip, which Ubuntu packages separately.
  if ! "${H3_PYTHON}" -c 'import venv, ensurepip' 2>/dev/null; then
    packages+=("$("${H3_PYTHON}" -c 'import sys; print("python%d.%d-venv" % sys.version_info[:2])')")
  fi
  if ((${#packages[@]})); then
    if ((EUID != 0)); then
      command -v sudo >/dev/null || fail "sudo required to install: ${packages[*]}"
      apt_prefix=(sudo)
    fi
    "${apt_prefix[@]}" apt-get update
    "${apt_prefix[@]}" apt-get install -y --no-install-recommends ca-certificates "${packages[@]}"
  fi
}

setup_env() {
  STAGE=system-packages
  install_system_packages
  STAGE=python-environment
  if [[ -d "${VENV_DIR}" ]]; then
    [[ -x "${PYTHON}" ]] || fail "Incomplete .venv; move it aside and rerun --setup"
    [[ "$("${PYTHON}" -c 'import sys; print(sys.version_info[:2])')" == "$("${H3_PYTHON}" -c 'import sys; print(sys.version_info[:2])')" ]] || fail "Existing .venv uses another Python version; move it aside before reinstalling"
  else
    "${H3_PYTHON}" -m venv "${VENV_DIR}"
  fi
  "${PYTHON}" -m pip install --upgrade 'pip>=25,<27'
  # Exact CUDA suffixes prevent the second resolver run from choosing PyPI CUDA 13 wheels.
  "${PYTHON}" -m pip install --prefer-binary -r requirements-torch.txt
  "${PYTHON}" -m pip install --prefer-binary -r requirements.txt
}

check_runtime() {
  STAGE=runtime
  [[ -x "${PYTHON}" ]] || fail "Virtual environment missing; run bash deploy.sh --setup"
  "${PYTHON}" -m pip check
  "${PYTHON}" verify_runtime.py
  "${PYTHON}" -m pip freeze > "${LOG_FILE%.log}-packages.txt"
}

download_model() {
  STAGE=download
  "${PYTHON}" download_model.py
}

test_generation() {
  STAGE=generation
  "${PYTHON}" generate.py --prompt "${H3_PROMPT}" --output "${H3_OUTPUT}" \
    --width 960 --height 544 --frames 124 --steps 9
  echo "Smoke test passed: ${H3_OUTPUT}"
}

case "${MODE}" in
  --setup) setup_env; check_runtime ;;
  --download) check_runtime; download_model ;;
  --test) check_runtime; test_generation ;;
  all) setup_env; check_runtime; download_model; test_generation ;;
esac
