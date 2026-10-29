#!/usr/bin/env bash
# Run a command and, if it fails, publish its last output lines as an annotation on the workflow run.
# Annotations stay readable from the API and the run summary even where raw job logs are not.
# Usage: .github/scripts/run-logged.sh <command> [args...]
set -uo pipefail
log="$(mktemp)"
"$@" 2>&1 | tee "${log}"
status=${PIPESTATUS[0]}
if [[ ${status} -ne 0 ]]; then
  "$(dirname "$0")/annotate.sh" "Last output lines (exit ${status})" < "${log}"
fi
exit "${status}"
