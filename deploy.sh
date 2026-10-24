#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "${PROJECT_DIR}"
MODE="${1:-all}"
fail() { echo "ERROR: $*" >&2; exit 1; }
usage() {
  cat <<'HELP'
Usage: bash deploy.sh [--prepare|--setup|--download|--check|--test|--test-all|--preflight|--help]
  (no flag)    Adapt environment, download full H3, then test all three GPU workflows.
  --prepare    Install dependencies + download model ahead of time; no GPU required.
  --setup      Install dependencies and test imports/codecs; no GPU required.
  --download   Resume model download using existing environment; no GPU required.
  --check      Offline GPU/runtime/cache readiness check; no model weights loaded.
  --test       Quick t2va GPU smoke test only; full H3 cache still required.
  --test-all   Offline GPU tests for t2va, fl2va and mixed-media ref2va.
  --preflight  Read-only hardware/disk checks; no installation or report files.
H3_TEST_TIMEOUT=600 optionally bounds EACH workflow loading + generation to 600 seconds.
HELP
}
[[ $# -le 1 ]] || { usage; exit 2; }
case "${MODE}" in
  all|--prepare|--setup|--preflight|--download|--check|--test|--test-all) ;;
  --help|-h) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac
STAGE=platform
SECONDS=0
STEP_STARTED=0
REPORT_FILE=''
ACCEPTANCE_PID=''
cancel_run() {
  local signum="$1" code="$2"
  trap '' INT TERM
  if [[ -n "${ACCEPTANCE_PID}" ]]; then
    kill -s "${signum}" "${ACCEPTANCE_PID}" 2>/dev/null || true
    wait "${ACCEPTANCE_PID}" || true
    ACCEPTANCE_PID=''
  fi
  exit "${code}"
}
finish() {
  local code=$? result=FAIL
  trap - EXIT
  if ((code == 0)); then result=PASS; fi
  if [[ -n "${REPORT_FILE}" ]]; then
    {
      printf 'mode=%s\nresult=%s\nexit_code=%s\nlast_stage=%s\nelapsed_seconds=%s\n' "${MODE}" "${result}" "${code}" "${STAGE}" "${SECONDS}"
      printf 'log=%s\nstages=%s\n' "${LOG_FILE}" "${STAGES_FILE}"
      if ((code == 0)) && [[ "${MODE}" == all || "${MODE}" == --test || "${MODE}" == --test-all ]]; then
        printf 'validated_acceptance_report=%s\n' "${ACCEPTANCE_REPORT}"
        if [[ "${MODE}" == --test ]]; then
          printf 'validated_output=%s\n' "${H3_OUTPUT}"
        fi
      fi
    } > "${REPORT_FILE}"
    printf 'RESULT: %s; mode=%s; stage=%s; elapsed=%ss; report=%s\n' "${result}" "${MODE}" "${STAGE}" "${SECONDS}" "${REPORT_FILE}"
    if ((code != 0)); then
      printf '%s\t%s\tFAIL(%s)\n' "${STAGE}" "$((SECONDS - STEP_STARTED))" "${code}" >> "${STAGES_FILE}"
      echo "Read the last stage in the log. Fix the cause and rerun the same mode; --test never downloads."
    fi
  fi
  exit "${code}"
}
trap finish EXIT
trap 'echo "ERROR: stage=${STAGE}, line=${LINENO}. See README.md." >&2' ERR
trap 'cancel_run INT 130' INT
trap 'cancel_run TERM 143' TERM
run_stage() {
  STAGE="$1"
  shift
  STEP_STARTED=${SECONDS}
  echo "== ${STAGE} =="
  "$@"
  if [[ -n "${REPORT_FILE}" ]]; then
    printf '%s\t%s\tPASS\n' "${STAGE}" "$((SECONDS - STEP_STARTED))" >> "${STAGES_FILE}"
  fi
}

# Validate OS before installation; prepare supports the same target OS without a GPU.
[[ -r /etc/os-release ]] || fail "Ubuntu x86_64 is required"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == ubuntu && "$(uname -m)" == x86_64 ]] || fail "Ubuntu x86_64 is required"
VENV_DIR="${PROJECT_DIR}/.venv"
PYTHON="${VENV_DIR}/bin/python"
# shellcheck source=scripts/environment.sh
source "${PROJECT_DIR}/scripts/environment.sh"
ALLOW_INSTALL=0
NEED_GPU=0
case "${MODE}" in all|--prepare|--setup) ALLOW_INSTALL=1 ;; esac
case "${MODE}" in all|--check|--test|--test-all|--preflight) NEED_GPU=1 ;; esac

if [[ "${MODE}" != --preflight ]]; then
  command -v flock >/dev/null || fail "flock missing; install util-linux"
  exec 9>"${PROJECT_DIR}/.cache-deploy.lock"
  flock -n 9 || fail "Another deployment/generation is running in this checkout"
  mkdir -p logs
  LOG_FILE="${PROJECT_DIR}/logs/deploy-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
  REPORT_FILE="${LOG_FILE%.log}-result.txt"
  STAGES_FILE="${LOG_FILE%.log}-stages.tsv"
  printf 'stage\tseconds\tresult\n' > "${STAGES_FILE}"
  exec > >(tee -a "${LOG_FILE}") 2>&1
  echo "Deployment log: ${LOG_FILE}"
fi
run_stage python-selection select_python "${ALLOW_INSTALL}"
echo "Selected Python: ${H3_PYTHON}"

export HF_HOME="${H3_HF_HOME:-${HF_HOME:-${PROJECT_DIR}/.cache/huggingface}}"
export HF_HUB_CACHE="${HF_HOME}/hub"
export PIP_CACHE_DIR="${H3_PIP_CACHE:-${PROJECT_DIR}/.cache/pip}"
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
H3_OUTPUT="${H3_OUTPUT:-${PROJECT_DIR}/outputs/smoke-test.mp4}"
H3_PROMPT="${H3_PROMPT:-A red ball rolls slowly to the right across a pale floor, with gentle rolling sounds and a soft tone.}"
H3_TEST_TIMEOUT="${H3_TEST_TIMEOUT:-0}"
[[ "${H3_TEST_TIMEOUT}" =~ ^(0|[1-9][0-9]{0,6})$ ]] || fail "H3_TEST_TIMEOUT must be an integer from 0 to 9999999 seconds"
# Zero means no deadline; never promise a generation duration before GPU measurements.


select_gpu() {
  local selector uuid
  selector="${H3_GPU_INDEX:-${CUDA_VISIBLE_DEVICES-0}}"
  [[ -n "${selector}" && "${selector}" != *,* && "${selector}" != -1 ]] || fail "Select one full GPU with H3_GPU_INDEX; multiple GPUs/MIG are unsupported"
  command -v nvidia-smi >/dev/null || fail "Host NVIDIA driver / nvidia-smi missing; use --prepare to stage files without a GPU"
  uuid="$(nvidia-smi -i "${selector}" --query-gpu=uuid --format=csv,noheader)"
  [[ "${uuid}" == GPU-* && "${uuid}" != *$'\n'* ]] || fail "A single full GPU is required"
  export CUDA_VISIBLE_DEVICES="${uuid}"
}
PREFLIGHT_FLAGS=()
if ((ALLOW_INSTALL == 1)) || [[ "${MODE}" == --preflight ]]; then PREFLIGHT_FLAGS+=(--install); fi
if ((NEED_GPU)); then
  run_stage gpu-selection select_gpu
  PREFLIGHT_FLAGS+=(--gpu "${CUDA_VISIBLE_DEVICES}")
else
  PREFLIGHT_FLAGS+=(--storage-only)
fi
run_stage preflight "${H3_PYTHON}" preflight.py --cache "${HF_HUB_CACHE}" --output "${H3_OUTPUT}" --prompt "${H3_PROMPT}" --environment "${PROJECT_DIR}" --pip-cache "${PIP_CACHE_DIR}" "${PREFLIGHT_FLAGS[@]}"
if [[ "${MODE}" == --preflight ]]; then
  echo "Hardware preflight passed; dependencies, model access and CUDA kernels are not tested."
  exit 0
fi
export TMPDIR="${PROJECT_DIR}/.cache/tmp"
mkdir -p "${TMPDIR}"

install_system_packages() {
  local packages=()
  if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then packages+=(ffmpeg); fi
  if [[ ! -s /etc/ssl/certs/ca-certificates.crt ]]; then packages+=(ca-certificates); fi
  if ! "${H3_PYTHON}" -c 'import venv, ensurepip' 2>/dev/null; then
    packages+=("$("${H3_PYTHON}" -c 'import sys; print("python%d.%d-venv" % sys.version_info[:2])')")
  fi
  if ((${#packages[@]})); then apt_install "${packages[@]}"; fi
}
setup_env() {
  if [[ -d "${VENV_DIR}" ]]; then
    [[ -x "${PYTHON}" ]] || fail "Incomplete .venv; move it aside and rerun --prepare"
    [[ "$("${PYTHON}" -c 'import sys; print(sys.version_info[:2])')" == "$("${H3_PYTHON}" -c 'import sys; print(sys.version_info[:2])')" ]] || fail ".venv and H3_PYTHON use different Python versions; move .venv aside to reinstall"
  else
    "${H3_PYTHON}" -m venv "${VENV_DIR}"
  fi
  "${PYTHON}" -m pip install --upgrade 'pip>=25,<27'
  "${PYTHON}" -m pip install --prefer-binary -r requirements-torch.txt
  "${PYTHON}" -m pip install --prefer-binary -r requirements.txt
}
check_runtime() {
  local flags=()
  [[ -x "${PYTHON}" ]] || fail "Run bash deploy.sh to install dependencies and download the model"
  "${PYTHON}" -m pip check
  if ((NEED_GPU == 0)); then flags+=(--cpu); fi
  "${PYTHON}" verify_runtime.py "${flags[@]}"
  "${PYTHON}" -m pip freeze > "${LOG_FILE%.log}-packages.txt"
}
check_cache() {
  "${PYTHON}" -c 'from download_model import local_snapshot; print("Complete local snapshot:", local_snapshot())'
  "${PYTHON}" verify_model.py
}
test_generation() {
  local scope=all status=0
  if [[ "${MODE}" == --test ]]; then scope=quick; fi
  ACCEPTANCE_REPORT="${LOG_FILE%.log}-acceptance.json"
  "${PYTHON}" acceptance.py --scope "${scope}" --output "${H3_OUTPUT}" \
    --report "${ACCEPTANCE_REPORT}" --prompt "${H3_PROMPT}" --timeout "${H3_TEST_TIMEOUT}" &
  ACCEPTANCE_PID=$!
  wait "${ACCEPTANCE_PID}" || status=$?
  ACCEPTANCE_PID=''
  return "${status}"
}

if ((ALLOW_INSTALL)); then
  run_stage system-packages install_system_packages
  run_stage dependencies setup_env
fi
if [[ "${MODE}" == --test || "${MODE}" == --test-all || "${MODE}" == --check ]]; then
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
fi
run_stage runtime check_runtime
case "${MODE}" in
  all|--prepare|--download) run_stage download "${PYTHON}" download_model.py ;;
esac
case "${MODE}" in
  all|--prepare|--download|--check|--test|--test-all) run_stage cache check_cache ;;
esac
case "${MODE}" in
  all|--test|--test-all)
    export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
    run_stage generation test_generation
    echo "GPU acceptance passed for the selected scope; see ${ACCEPTANCE_REPORT}" ;;
  --check) echo "READY: GPU runtime and cached files passed; full model inference is still untested." ;;
  --prepare|--download) echo "PREPARED: no GPU inference performed. On the GPU server run --check, then --test-all (--test is a quick t2va-only check)." ;;
  --setup) echo "SETUP: imports/codecs passed; model download and GPU inference are still pending." ;;
esac
