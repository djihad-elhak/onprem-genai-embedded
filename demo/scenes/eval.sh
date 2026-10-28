#!/usr/bin/env bash
# The evaluation suite checks itself, then compares the two models measured on Kaggle.
source "$(dirname "$0")/_lib.sh"
say "27 embedded-C tasks: every reference passes, every seeded fault is caught"
run "oge eval validate | tail -12"
say "Models measured on 2x T4 (benchmark run 2), scored by compiling and running their answers"
run "oge eval report docs/results/bench/run2-2026-10-28/eval/*.json --out artifacts/demo/eval.md > /dev/null && python -m rich.markdown -w 118 artifacts/demo/eval.md"
