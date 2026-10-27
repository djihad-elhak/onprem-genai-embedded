#!/usr/bin/env bash
# Fetch the pinned NASA F´ release used as the target codebase (not redistributed in this repo).
# Usage: scripts/fetch_fprime.sh [destination]   (default: third_party/fprime)
set -euo pipefail

FPRIME_TAG="v4.4.1"
FPRIME_COMMIT="558b7ef48edd5d25f3bdddcbbe7afddb9cc22d09"
DEST="${1:-third_party/fprime}"

if [[ -d "${DEST}/.git" ]]; then
  current="$(git -C "${DEST}" rev-parse HEAD)"
  if [[ "${current}" == "${FPRIME_COMMIT}" ]]; then
    echo "F´ ${FPRIME_TAG} already present at ${DEST}"
    exit 0
  fi
  echo "error: ${DEST} exists at ${current}, expected ${FPRIME_COMMIT}" >&2
  exit 1
fi

mkdir -p "$(dirname "${DEST}")"
git -c advice.detachedHead=false clone --quiet --depth 1 --branch "${FPRIME_TAG}" \
  https://github.com/nasa/fprime "${DEST}"
actual="$(git -C "${DEST}" rev-parse HEAD)"
if [[ "${actual}" != "${FPRIME_COMMIT}" ]]; then
  echo "error: tag ${FPRIME_TAG} resolved to ${actual}, expected ${FPRIME_COMMIT}" >&2
  exit 1
fi
# googletest is only needed to build/run F´ unit tests (agent work package)
if [[ "${WITH_SUBMODULES:-0}" == "1" ]]; then
  git -C "${DEST}" submodule update --quiet --init --recursive --depth 1
fi
echo "F´ ${FPRIME_TAG} (${FPRIME_COMMIT}) fetched to ${DEST}"
