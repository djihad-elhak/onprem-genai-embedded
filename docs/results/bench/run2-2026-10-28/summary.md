# Benchmark summary

repo commit `a91bbdb52587f9836416b9ead8b4cc32a1ae7da6 (embedded wheel sha256 128f5d4b163bd96f)` · GPUs ['Tesla T4, 15360 MiB, 580.178.04', 'Tesla T4, 15360 MiB, 580.178.04'] · elapsed 3.36 h

## Traceability recovery

| method | MAP | MRR | R@1 | R@10 |
|---|---|---|---|---|
| bm25 | 0.488 | 0.591 | 0.297 | 0.677 |
| graph | 0.249 | 0.291 | 0.073 | 0.550 |
| graph+bm25 | 0.569 | 0.665 | 0.330 | 0.781 |
| dense | 0.479 | 0.586 | 0.261 | 0.713 |
| graph+dense | 0.573 | 0.680 | 0.303 | 0.817 |
| graph+rrf(bm25,dense) | 0.609 | 0.713 | 0.350 | 0.821 |
| graph+rrf(bm25,dense)+llm-rerank@10 | 0.584 | 0.670 | 0.297 | 0.822 |

## Serving (chat profile)

| config | conc. | out tok/s | TTFT p50 s | TPOT p50 ms |
|---|---|---|---|---|
| devstral-small-2-24b__llamacpp | 1 | 12.9 | 4.86 | 67.5 |
| devstral-small-2-24b__llamacpp | 2 | 23.7 | 1.28 | 81.5 |
| devstral-small-2-24b__llamacpp | 4 | 25.6 | 2.22 | 151.1 |
| devstral-small-2-24b__llamacpp | 8 | 23.0 | 68.38 | 150.9 |
| devstral-small-2-24b__llamacpp | 16 | 23.5 | 188.17 | 148.4 |
| qwen3-coder-30b-a3b__llamacpp | 1 | 54.8 | 2.21 | 13.7 |
| qwen3-coder-30b-a3b__llamacpp | 2 | 82.7 | 0.73 | 22.5 |
| qwen3-coder-30b-a3b__llamacpp | 4 | 105.9 | 1.15 | 35.0 |
| qwen3-coder-30b-a3b__llamacpp | 8 | 83.5 | 18.14 | 35.2 |
| qwen3-coder-30b-a3b__llamacpp | 16 | 84.4 | 48.98 | 35.3 |
| qwen3-coder-30b-a3b__vllm | 1 | 54.1 | 2.11 | 14.3 |
| qwen3-coder-30b-a3b__vllm | 2 | 88.2 | 0.11 | 22.3 |
| qwen3-coder-30b-a3b__vllm | 4 | 130.2 | 0.19 | 30.3 |
| qwen3-coder-30b-a3b__vllm | 8 | 115.5 | 1.13 | 52.9 |
| qwen3-coder-30b-a3b__vllm | 16 | 133.2 | 1.69 | 86.8 |

## Model evaluation (embedded C, scored by execution)

| Model | Generate pass@1 | Test-gen pass@1 (mutation score) | Refactor pass@1 (CCN↓) | Document pass@1 | Overall | Latency / task |
|---|---|---|---|---|---|---|
| devstral-small-2-24b__llamacpp | 42% | 17% (30%) | 40% (48%) | 50% | 37% | 100 s |
| qwen3-coder-30b-a3b__llamacpp | 75% | 0% (26%) | 40% (54%) | 100% | 54% | 23 s |


## Test-generation agent (F´ requirement gaps)

| config | targets | verified | not testable | suspected defect | verified rate | 1st-try compile | attempts | mutants killed |
|---|---|---|---|---|---|---|---|---|
| devstral-small-2-24b__llamacpp | 28 | 8 | 1 | 0 | 29% | 15% | 2.125 | 21/32 |
| qwen3-coder-30b-a3b__llamacpp | 28 | 11 | 0 | 0 | 39% | 52% | 1.3636 | 25/41 |
