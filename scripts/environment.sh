#!/usr/bin/env bash
# Sourced by deploy.sh. Does not change the system python3 symlink or add apt repositories.

supported_python() {
  command -v "$1" >/dev/null && "$1" -c 'import sys; sys.exit(not ((3, 11) <= sys.version_info[:2] <= (3, 13) and sys.version_info.releaselevel == "final"))' 2>/dev/null
}

apt_install() {
  local prefix=()
  if ((EUID != 0)); then
    command -v sudo >/dev/null || fail "Need root/sudo to install missing packages: $*"
    # Fail promptly in unattended sessions, rather than wait for a password.
    sudo -n true || fail "Missing packages require sudo; run sudo -v in your terminal first, then retry"
    prefix=(sudo -n)
  fi
  if [[ "${APT_UPDATED:-0}" != 1 ]]; then
    "${prefix[@]}" apt-get update
    APT_UPDATED=1
  fi
  if (($#)); then
    "${prefix[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
  fi
}

select_python() {
  local allow_install="$1" candidate version
  if [[ -n "${H3_PYTHON:-}" ]]; then
    supported_python "${H3_PYTHON}" || fail "H3_PYTHON must name a working Python 3.11–3.13 interpreter"
    return
  fi
  if [[ -d "${VENV_DIR}" ]]; then
    supported_python "${VENV_DIR}/bin/python" || fail "Existing .venv is incomplete/unsupported; move it aside and rerun --prepare"
    H3_PYTHON="${VENV_DIR}/bin/python"
    return
  fi
  for candidate in python3.12 python3.11 python3.13 python3; do
    if supported_python "${candidate}"; then
      H3_PYTHON="${candidate}"
      return
    fi
  done
  [[ "${allow_install}" == 1 ]] || fail "Python environment missing; run bash deploy.sh to install dependencies and download the model"
  apt_install
  for version in 3.12 3.11 3.13; do
    # Both interpreter and matching venv must exist in the configured apt sources.
    if apt-cache policy "python${version}" | awk '$1 == "Candidate:" && $2 != "(none)" && $2 !~ /~(rc|a|b)[0-9]/ { found=1 } END { exit !found }' &&
       apt-cache policy "python${version}-venv" | awk '$1 == "Candidate:" && $2 != "(none)" && $2 !~ /~(rc|a|b)[0-9]/ { found=1 } END { exit !found }'; then
      apt_install "python${version}" "python${version}-venv" ca-certificates
      H3_PYTHON="python${version}"
      supported_python "${H3_PYTHON}" || fail "Installed interpreter failed validation"
      return
    fi
  done
  fail "Configured Ubuntu apt sources have no Python 3.11–3.13 + venv pair. Use Ubuntu 24.04 or provide H3_PYTHON; no external PPA was added"
}
