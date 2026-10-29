#!/usr/bin/env bash
# Publish stdin (last 60 lines, long lines cut) as one error annotation on the workflow run.
# Usage: <command> | .github/scripts/annotate.sh "Title"
set -uo pipefail
tail -n 60 | cut -c1-400 | TITLE="${1:-Output}" python3 -c '
import os, sys
text = sys.stdin.read().replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
print("::error title=" + os.environ["TITLE"] + "::" + text)'
