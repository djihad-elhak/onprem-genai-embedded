# Results

Every number in the README comes from a file in this directory, produced by a committed command or notebook.
F´ commit for all knowledge results: `558b7ef48edd5d25f3bdddcbbe7afddb9cc22d09` (tag v4.4.1).

| File | Content | Produced by |
|---|---|---|
| `traceability_lexical.json` | Requirement→test recovery: BM25, graph, graph-constrained BM25 (151 requirements × 3,261 tests, per-requirement metrics, bootstrap CIs) | `oge knowledge trace-eval --out …` (CPU) |
| `traceability_audit.json` | Tags citing undefined requirement IDs; tags citing another module's requirements (with file:line) | `oge knowledge ingest --audit-out …` |
| `traceability_gaps.json` | Requirements specified as verified by test without an explicit test tag, with 3 suggested candidate tests each | `oge knowledge gaps --out …` |
| `probe/` | 2× T4 compatibility matrix: load status, VRAM, TTFT, decode/prefill speed, 4× concurrency, C smoke test | `kaggle/00_probe_t4x2` |
| `bench/` | Serving sweeps (3 profiles × concurrency), model configs for sizing, dense / hybrid / LLM-reranked traceability, `oge eval` reports, agent runs (results, summaries, generated tests as patches) | `kaggle/01_benchmark` |

Reproduce the CPU results:

```bash
scripts/fetch_fprime.sh
uv run oge knowledge ingest --audit-out docs/results/traceability_audit.json
uv run oge knowledge trace-eval --out docs/results/traceability_lexical.json
uv run oge knowledge gaps --out docs/results/traceability_gaps.json
```
