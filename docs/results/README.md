# Results

Every number in the README comes from a file in this directory, produced by a committed command or notebook.
F´ commit for all knowledge results: `558b7ef48edd5d25f3bdddcbbe7afddb9cc22d09` (tag v4.4.1).

| File | Content | Produced by |
|---|---|---|
| `traceability_lexical.json` | Requirement→test recovery: BM25, graph, graph-constrained BM25 (151 requirements × 3,261 tests, per-requirement metrics, bootstrap CIs) | `oge knowledge trace-eval --out …` (CPU) |
| `traceability_audit.json` | Tags citing undefined requirement IDs; tags citing another module's requirements (with file:line) | `oge knowledge ingest --audit-out …` |
| `traceability_gaps.json` | Requirements specified as verified by test without an explicit test tag, with 3 suggested candidate tests each | `oge knowledge gaps --out …` |
| `probe/` | 2× T4 compatibility matrix: load status, VRAM, TTFT, decode/prefill speed, 4× concurrency, C smoke test, root causes of failures — run 1 (llama.cpp build failed) and run 2 (complete) | `kaggle/00_probe_t4x2` |
| `bench/run1-2026-10-28.md` | Failed run: GPU memory held by the embedding step (cause and fix) | `kaggle/01_benchmark` |
| `bench/run2-2026-10-28/` | **Final**: dense / hybrid / LLM-reranked traceability, `oge eval` reports for 2 models (with the generated code), official model configs for sizing. **Superseded**: serving sweeps (cache-served levels) and agent v1 (baseline of the failure analysis) | `kaggle/01_benchmark` at `a91bbdb` |
| `bench/run3-2026-10-28/` | **Final**: serving sweeps on new prompts at every level (3 profiles × 5 concurrency levels × 3 deployments), agent v2 (records, patches, review sheets, AI pre-review) | `kaggle/01_benchmark` at `bf66c9d`, `STAGES=["serving", "agent"]` |
| `sizing/` | Calibration of the sizing model (llama.cpp and vLLM on T4, dense and MoE fitted separately), leave-one-model-out and load-test validation, team tables | `oge sizing calibrate / capacity / report` |

Reproduce the CPU results:

```bash
scripts/fetch_fprime.sh
uv run oge knowledge ingest --audit-out docs/results/traceability_audit.json
uv run oge knowledge trace-eval --out docs/results/traceability_lexical.json
uv run oge knowledge gaps --out docs/results/traceability_gaps.json
```
