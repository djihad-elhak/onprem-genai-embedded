#!/usr/bin/env bash
# Run a command and, if it fails, publish its last output lines as an annotation on the workflow run.
# Annotations stay readable from the API and the run summary even where raw job logs are not.
# Usage: .github/scripts/run-logged.sh <command> [args...]
set -uo pipefail
log="$(mktemp)"
"$@" 2>&1 | tee "${log}"
status=${PIPESTATUS[0]}
if [[ ${status} -ne 0 ]]; then
  tail -n 40 "${log}" | STATUS="${status}" python3 -c '
import os, sys
text = sys.stdin.read().replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
status = os.environ["STATUS"]
print(f"::error title=Last output lines (exit {status})::{text}")'
fi
exit "${status}"
