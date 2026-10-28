#!/usr/bin/env bash
# The repair loop: the first answer misspells a harness macro (scripted mistake); the compiler error and a
# did-you-mean hint go back to the model, the second answer builds and passes.
source "$(dirname "$0")/_lib.sh"
say "Repair loop — scripted answers: the first one misspells a harness macro on purpose"
run oge agent run --scripted tests/data/scripted_agent_answers.json -r SVC-COMSTUB-003 \
    --branch oge-agent/demo-repair --out artifacts/demo/repair.jsonl --trace
