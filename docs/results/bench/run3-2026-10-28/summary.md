# Benchmark summary

repo commit `bf66c9d1ae03927c09d6103589d753effd408342 (embedded wheel sha256 662c6d4741659f6d)` · GPUs ['Tesla T4, 15360 MiB, 580.178.04', 'Tesla T4, 15360 MiB, 580.178.04'] · elapsed 2.75 h

## Traceability recovery

| method | MAP | MRR | R@1 | R@10 |
|---|---|---|---|---|
| bm25 | 0.488 | 0.591 | 0.297 | 0.677 |
| graph | 0.249 | 0.291 | 0.073 | 0.550 |
| graph+bm25 | 0.569 | 0.665 | 0.330 | 0.781 |

## Serving (chat profile)

| config | conc. | out tok/s | TTFT p50 s | TPOT p50 ms |
|---|---|---|---|---|
| devstral-small-2-24b__llamacpp | 1 | 12.7 | 5.04 | 65.8 |
| devstral-small-2-24b__llamacpp | 2 | 19.4 | 8.62 | 81.4 |
| devstral-small-2-24b__llamacpp | 4 | 21.7 | 11.16 | 155.5 |
| devstral-small-2-24b__llamacpp | 8 | 21.7 | 82.37 | 165.0 |
| devstral-small-2-24b__llamacpp | 16 | 21.7 | 226.25 | 165.8 |
| qwen3-coder-30b-a3b__llamacpp | 1 | 51.3 | 2.32 | 13.6 |
| qwen3-coder-30b-a3b__llamacpp | 2 | 59.4 | 3.94 | 23.5 |
| qwen3-coder-30b-a3b__llamacpp | 4 | 69.7 | 5.68 | 43.4 |
| qwen3-coder-30b-a3b__llamacpp | 8 | 68.0 | 26.48 | 52.1 |
| qwen3-coder-30b-a3b__llamacpp | 16 | 69.0 | 70.68 | 50.0 |
| qwen3-coder-30b-a3b__vllm | 1 | 49.3 | 2.38 | 14.0 |
| qwen3-coder-30b-a3b__vllm | 2 | 58.2 | 3.72 | 24.6 |
| qwen3-coder-30b-a3b__vllm | 4 | 73.8 | 6.79 | 37.3 |
| qwen3-coder-30b-a3b__vllm | 8 | 86.6 | 9.43 | 71.2 |
| qwen3-coder-30b-a3b__vllm | 16 | 98.0 | 7.03 | 142.4 |

## Test-generation agent (F´ requirement gaps)

| config | targets | verified | not testable | suspected defect | verified rate | 1st-try compile | attempts | mutants killed |
|---|---|---|---|---|---|---|---|---|
| devstral-small-2-24b__llamacpp | 28 | 18 | 0 | 0 | 64% | 67% | 1.3333 | 35/67 |
| qwen3-coder-30b-a3b__llamacpp | 28 | 18 | 0 | 0 | 64% | 81% | 1.5556 | 42/64 |
