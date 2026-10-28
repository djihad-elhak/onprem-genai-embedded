#!/usr/bin/env bash
# Prepare the pinned F´ checkout for unit-test builds (needed by the test-generation agent):
#   1. googletest submodule, 2. minimal F´ tool venv (pinned to the versions F´ v4.4.1 requires),
#   3. unit-test build cache (`fprime-util generate --ut`).
# Usage: scripts/setup_fprime_ut.sh [fprime_dir]   (default: third_party/fprime)
set -euo pipefail

FPRIME_DIR="${1:-third_party/fprime}"
VENV="$(dirname "${FPRIME_DIR}")/fprime-venv"

WITH_SUBMODULES=1 "$(dirname "$0")/fetch_fprime.sh" "${FPRIME_DIR}"
git -C "${FPRIME_DIR}" submodule update --quiet --init --recursive --depth 1

if [[ ! -x "${VENV}/bin/fprime-util" ]]; then
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install --quiet --upgrade pip
  # versions pinned by F´ v4.4.1 requirements.txt (build tools only, no ground system)
  "${VENV}/bin/pip" install --quiet "fprime-tools==4.4.0" "fprime-fpp==3.4.0" "cmake==3.26.0" "ninja==1.11.1.4"
fi

if [[ ! -d "${FPRIME_DIR}/build-fprime-automatic-native-ut" ]]; then
  (cd "${FPRIME_DIR}" && PATH="$(cd "${VENV}" && pwd)/bin:${PATH}" fprime-util generate --ut)
fi
echo "F´ unit-test build ready: ${FPRIME_DIR} (tools: ${VENV}/bin)"
