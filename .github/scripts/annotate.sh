#!/usr/bin/env bash
# Publish the end of stdin (about 3.5 kB, long lines cut) as one error annotation on the workflow run.
# Usage: <command> | .github/scripts/annotate.sh "Title"
set -uo pipefail
tail -n 80 | cut -c1-300 | TITLE="${1:-Output}" python3 -c '
import os, sys
text = sys.stdin.read()[-3500:]  # GitHub keeps about 4 kB of an annotation: keep the end
text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
print("::error title=" + os.environ["TITLE"] + "::" + text)'
