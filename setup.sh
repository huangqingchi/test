#!/usr/bin/env bash
# One-command environment setup for the supported Ubuntu deployment host.
set -Eeuo pipefail

case "${1:-}" in
  --help|-h)
    echo "Usage: bash setup.sh"
    echo "Ubuntu x86_64: select/install Python, create .venv, install pinned dependencies, and verify imports/codecs."
    echo "No model download or GPU inference. Optional environment: H3_PYTHON, H3_PIP_CACHE, H3_HF_HOME."
    exit 0 ;;
esac
if (($#)); then
  echo "Usage: bash setup.sh (no arguments); use deploy.sh for model download/testing." >&2
  exit 2
fi
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${PROJECT_DIR}/deploy.sh" --setup
