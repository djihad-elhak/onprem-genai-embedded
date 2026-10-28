#!/usr/bin/env bash
# The test-generation agent closes one F´ traceability gap, with Qwen3-Coder's real answer from benchmark run 3.
source "$(dirname "$0")/_lib.sh"
say "F´ requirements specified as 'verified by unit test' but cited by no test (Svc/ComStub)"
run oge agent targets -m Svc/ComStub
say "Close SVC-COMSTUB-007 — model answer replayed from the Kaggle run (Qwen3-Coder-30B-A3B), everything else live"
run oge agent run --scripted demo/qwen3-coder-run3-replay.json --label Qwen3-Coder-30B-A3B \
    -r SVC-COMSTUB-007 --mutants 4 --branch oge-agent/demo --out artifacts/demo/agent.jsonl --trace
say "One commit on a review branch, test files only, with an AI-use disclosure"
run "git -C third_party/fprime log -1 --stat --format='%an%n%B' | grep -v '^$'"
