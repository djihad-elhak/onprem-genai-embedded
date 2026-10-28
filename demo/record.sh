#!/usr/bin/env bash
# Record the demo scenes (asciinema) and render them as GIFs for the README (agg).
#   demo/record.sh [scene ...]      scenes: agent repair mcp eval (default: all)
# Needs: asciinema (pip), agg (github.com/asciinema/agg), an F´ checkout with its UT build (setup_fprime_ut.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
AGG=${AGG:-agg}
mkdir -p demo/casts docs/assets artifacts/demo
reset_fprime() {
  git -C third_party/fprime checkout -q --detach 558b7ef
  git -C third_party/fprime branch --list 'oge-agent/demo*' | xargs -r git -C third_party/fprime branch -q -D
  rm -f artifacts/demo/*.jsonl artifacts/demo/*.json artifacts/demo/*.md
}
for scene in "${@:-agent repair mcp eval}"; do
  for s in $scene; do
    reset_fprime
    asciinema rec --overwrite -q --cols 120 --rows 34 -i 1.5 -c "bash demo/scenes/$s.sh" "demo/casts/$s.cast"
    "$AGG" --font-size 14 --theme monokai --speed 1.2 "demo/casts/$s.cast" "docs/assets/demo-$s.gif"
  done
done
reset_fprime
