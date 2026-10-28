# Benchmark run 2 — Kaggle 2× Tesla T4

- Notebook `kaggle/01_benchmark` at commit `eaa641d` (standalone wheel), all stages · 2026-10-28 · 3.36 h
- llama.cpp `a7af149` (b11953, CUDA, SM 7.5) · vLLM 0.32.0 · 2× Tesla T4 16 GB, driver 580
- Configurations: Qwen3-Coder-30B-A3B and Devstral-Small-2-24B, both Q4_K_M on llama.cpp (4 slots × 16k
  context); Qwen3-Coder-30B-A3B AWQ on vLLM (tensor parallel 2), serving only

| Output | Status |
|---|---|
| Traceability: lexical, dense, hybrid, LLM rerank (`traceability.json`) | **final** |
| Model evaluation, 27 embedded C tasks (`eval/`) | **final** |
| Official model configs for the sizing calculator (`model_configs/`) | **final**, imported into `sizing/data/models.yaml` |
| Serving sweeps (`serving-superseded/`) | **superseded by run 3**: levels 2 and 4 were served from cache (below) |
| Test-generation agent v1 (`agent-v1/`) | **superseded by run 3** (agent v2); kept as the baseline of the failure analysis |

## Traceability recovery

151 requirements × 3,261 test cases, tags and IDs masked; mean over requirements, 95 % bootstrap CI.

| Method | MAP | MRR | Recall@1 | Recall@10 | nDCG@10 |
|---|---|---|---|---|---|
| Graph only | 0.249 [0.220, 0.278] | 0.291 | 0.073 | 0.550 | 0.320 |
| Dense (Qwen3-Embedding-0.6B) | 0.479 [0.428, 0.531] | 0.586 | 0.261 | 0.713 | 0.560 |
| BM25 | 0.488 [0.427, 0.548] | 0.591 | 0.297 | 0.677 | 0.554 |
| Graph-constrained BM25 | 0.569 [0.513, 0.626] | 0.665 | 0.330 | 0.781 | 0.644 |
| Graph-constrained dense | 0.573 [0.521, 0.619] | 0.680 | 0.303 | 0.817 | 0.661 |
| **Graph-constrained RRF(BM25, dense)** | **0.609 [0.553, 0.660]** | **0.713** | **0.350** | 0.821 | **0.688** |
| + LLM rerank of the top 10 (Qwen3-Coder, 0–10 score) | 0.584 [0.535, 0.633] | 0.670 | 0.297 | 0.822 | 0.666 |

- Dense and lexical retrieval are equally good alone (MAP 0.48–0.49) but fail on different requirements: their
  rank fusion inside the graph prior is the best method, +0.04 MAP over graph-constrained BM25.
- Pointwise LLM reranking **lowers** precision at the top (Recall@1 0.350 → 0.297): the judge scores each pair
  without the module prior and gives many ties. It costs 10 LLM calls per requirement (644 s for 151) and is
  not used by default.
- The embedding pass (3,261 tests + 151 queries, fp32, batch 8) took 486 s in a child process; GPU memory was
  back to 0 MiB afterwards (`dataset.gpu_mib_after_embedding`), so the fix of run 1 worked.

## Model evaluation (`oge eval`, one sample per task)

| Model | Generate (12) | Unit-test gen. (6) | Refactor (5) | Document (4) | Tasks passed | Median latency / task |
|---|---|---|---|---|---|---|
| **Qwen3-Coder-30B-A3B** | **9 (75 %)** | 0 · 2 valid, 7/9 mutants | 2 (40 %) | **4 (100 %)** | **15 / 27** | **21 s** |
| Devstral-Small-2-24B | 5 (42 %) | 1 · 2 valid, 9/10 mutants | 2 (40 %) | 2 (50 %) | 10 / 27 | 85 s |

Unit-test generation passes when the test program passes on the correct implementation **and** kills every
seeded mutant; "valid" tests pass on the correct implementation.

Paired on the same tasks: 7 tasks passed by Qwen3-Coder only, 2 by Devstral only (exact McNemar p = 0.18). With
27 tasks and one sample each this is a direction, not a significant difference; the 4× latency gap is not in
doubt. Every failure was re-scored locally from the stored outputs (`eval/*.json`, field `code`) to check that
it is the model's error, not the harness's:

- **Unit-test generation — wrong oracles.** 8 of 12 test programs fail on the *correct* implementation because
  the model computed expected values by hand and got them wrong (Fletcher-16 checksums, saturating-subtraction
  bounds, moving average after the window wraps, CCSDS length field). The valid tests are good (16 of 19
  mutants killed). This is the strongest argument for execution-based gates on generated tests.
- **Generation — bit-level conventions.** Both models fail COBS (blocks of 254 bytes), the convolutional
  encoder (bit packing) and Hamming(7,4) (bit layout), although each specification states the convention.
  Devstral also fails the CCSDS header bit fields, CRC-32 and 32-bit tick wrap-around, and once forgets
  `#include <stddef.h>`.
- **Refactoring — behaviour drift.** Complexity always went down (max CCN −54 % / −48 %), but Qwen3-Coder's
  three failed refactorings changed behaviour (error precedence in a validator, mode-transition counting,
  telemetry byte layout); of Devstral's three, one changed behaviour and two do not compile.
- **Documentation.** Devstral skipped the `static` helper functions (completeness 0.71 and 0.79).

## Serving sweeps — superseded

Concurrency levels 1, 2 and 4 sent the **same 8 requests**, so levels 2 and 4 were answered from the servers'
prompt / prefix cache. The vLLM agent profile shows it: 2.5 → 35.6 → 48.6 tok/s at 1 → 2 → 4 streams (time to
first token 8.8 s → 0.26 s on 9.7k-token prompts), then 6.6 tok/s at 8 streams on new requests. Fixed in
`ce8bd6e` (every level uses new requests that start at random lines of the corpus); re-measured in run 3.

## Agent v1 — superseded, baseline of agent v2

| Model | Verified | Not testable | First answer compiles | Median time / requirement | Mutants killed by verified tests |
|---|---|---|---|---|---|
| Qwen3-Coder-30B-A3B | 11 / 28 (39 %) | 0 | 52 % | 38 s | 25 / 41 (61 %) |
| Devstral-Small-2-24B | 8 / 28 (29 %) | 1 | 15 % | 113 s | 21 / 32 (66 %) |

Failed attempts by primary cause (`agent.runner.failure_causes`, first matching rule):

| Cause | Qwen3-Coder | Devstral |
|---|---|---|
| Dispatch call on the wrong object or on a passive component (`doDispatch`, `dispatchAll`, `this->component` in PrmDb) | 23 (11 req.) | 42 (19 req.) |
| Namespace-qualified method definition (`void Svc::X::f()` → declaration `void Svc::f();`) — **agent bug** | 8 (4 req.) | 0 |
| Answer missing a block (repair answers resent only the changed block) | 5 | 0 |
| Reused an existing method or test name | 5 | 0 |
| `-Werror`: C-style cast or deprecated API | 0 | 4 |
| Other compile errors (invented enum values and include paths, a macro called as `this->ASSERT_…`) | 1 | 13 |
| F´ assertion in the component (test broke a precondition) | 6 | 1 |
| Wrong expected value | 7 | 6 |
| **Total failed attempts** | **55** | **66** |

Half of all failed attempts came from one confusion that the agent itself reinforced: the system prompt
described `this->component.doDispatch()` for active components without saying which kind the component under
test is (three of the four are passive), and the did-you-mean hints offered `dispatchAll`, a name that does not
exist in F´ v4. Agent v2 (`ce8bd6e`) states the component kind and the exact dispatch call in the task, stops
suggesting `dispatchAll`, fixes the qualified-definition bug, reuses the block a repair answer leaves out,
shows the asserted source line for F´ assertions and states the `-Werror` rules. Replaying Qwen3-Coder's last
answer for SVC-COMSTUB-004 through the fixed patcher: it builds and passes.

## Reproduce

```bash
python scripts/build_kaggle_notebook.py kaggle/01_benchmark.py --standalone --out 01_benchmark.ipynb  # at eaa641d
uv run oge eval report docs/results/bench/run2-2026-10-28/eval/*.json
uv run oge agent report docs/results/bench/run2-2026-10-28/agent-v1/qwen3-coder-30b-a3b__llamacpp.jsonl
```
