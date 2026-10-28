# Benchmark run 3 — Kaggle 2× Tesla T4: serving on new prompts, agent v2

- Notebook `kaggle/01_benchmark` at commit `bf66c9d`, `STAGES = ["serving", "agent"]` · 2026-10-28 · 2.75 h
- llama.cpp `a7af149` (b11953) · vLLM 0.32.0 · 2× Tesla T4 16 GB
- Same configurations as run 2: Qwen3-Coder-30B-A3B and Devstral-Small-2-24B, Q4_K_M on llama.cpp (4 slots ×
  16k context), Qwen3-Coder-30B-A3B AWQ on vLLM (tensor parallel 2). Traceability, `oge eval` and the model
  configs are those of run 2 (unchanged code).

## Serving (`serving/`)

Every concurrency level sends new requests (`first_request` in each level), so no level is answered from a cache
warmed by an earlier one; the agent profile's ≈ 7k-token repository prefix is shared on purpose. Each server
got one warm-up request per profile outside the measured range. No request failed.

**IDE chat** (≈ 2.5k-token prompt, 400-token answer): total output tok/s · per-user decode speed · median
time to first token.

| Deployment | 1 stream | 2 streams | 4 streams | 8 streams | 16 streams |
|---|---|---|---|---|---|
| Qwen3-Coder · llama.cpp | 51 · 74/user · 2.3 s | 59 · 43/user · 3.9 s | 70 · 23/user · 5.7 s | 68 · 19/user · 26.5 s | 69 · 20/user · 70.7 s |
| Qwen3-Coder · vLLM | 49 · 71/user · 2.4 s | 58 · 41/user · 3.7 s | 74 · 27/user · 6.8 s | 87 · 14/user · 9.4 s | 98 · 7/user · 7.0 s |
| Devstral · llama.cpp | 13 · 15/user · 5.0 s | 19 · 12/user · 8.6 s | 22 · 6/user · 11.2 s | 22 · 6/user · 82.4 s | 22 · 6/user · 226.2 s |

**Agent step** (≈ 9k-token prompt, mostly a shared prefix; ≈ 30-token action): requests/s · median time to first
token.

| Deployment | 1 stream | 2 streams | 4 streams | 8 streams | 16 streams |
|---|---|---|---|---|---|
| Qwen3-Coder · llama.cpp | 0.29 · 2.0 s | 0.33 · 2.0 s | 0.31 · 4.1 s | 0.38 · 12.2 s | 0.44 · 27.7 s |
| Qwen3-Coder · vLLM | 0.10 · 7.7 s | 0.13 · 7.7 s | 0.13 · 19.1 s | 0.13 · 30.4 s | 0.14 · 31.6 s |
| Devstral · llama.cpp | 0.14 · 3.7 s | 0.12 · 3.9 s | 0.14 · 7.5 s | 0.20 · 22.3 s | 0.20 · 59.3 s |

**Inline completion** (≈ 1k-token prompt, ≈ 60-token answer): median time to first token · requests/s.

| Deployment | 1 stream | 2 streams | 4 streams | 8 streams | 16 streams |
|---|---|---|---|---|---|
| Qwen3-Coder · llama.cpp | 1.06 s · 0.58 | 1.22 s · 0.68 | 2.64 s · 0.74 | 6.23 s · 0.76 | 17.86 s · 0.70 |
| Qwen3-Coder · vLLM | 0.67 s · 0.77 | 0.65 s · 1.01 | 1.54 s · 1.10 | 2.27 s · 1.42 | 2.28 s · 1.51 |
| Devstral · llama.cpp | 2.50 s · 0.15 | 3.58 s · 0.20 | 4.44 s · 0.24 | 19.27 s · 0.25 | 50.15 s · 0.25 |

What it shows:

- **llama.cpp stops scaling at its slot count.** With 4 slots, requests 5–16 wait in a queue: time to first
  token goes from 5.7 s to 71 s for chat while throughput stays flat. vLLM keeps batching (98 tok/s at 16
  streams, first token in 7 s), but each user then gets 7 tok/s.
- **At a 20 tok/s-per-user target, one 2× T4 server holds about 4 concurrent chat users** with either engine
  (≈ 0.17–0.19 chat requests/s). The sizing planner predicts 0.187 requests/s for llama.cpp
  (`docs/results/sizing`).
- **The best engine depends on the workload on this GPU.** vLLM is better for interactive traffic (completion
  first token 0.7–2.3 s vs 1–18 s, up to twice the requests/s). llama.cpp is 3× better for long-context agent steps,
  because vLLM's prompt processing on Turing (no FlashAttention 2, no Marlin kernels for AWQ) runs at ≈ 150–450
  tok/s on these prompts according to its own logs. On Ampere / Hopper GPUs this has to be re-measured.
- **Devstral (dense 24B) is 2–4× slower than the MoE on every profile** and does not reach 20 tok/s even for a
  single user (15 tok/s) on this hardware.
- Run 2's cached levels overstated throughput by up to 10× (vLLM agent profile at 2 streams: 35.6 tok/s then,
  3.6 now).

## Test-generation agent v2 (`agent-v2/`)

Same 28 requirement gaps, same models, same context budget as agent v1 (run 2).

| Model | Verified v1 → v2 | First answer compiles | Attempts when verified | Mutants killed by verified tests | Median time / requirement |
|---|---|---|---|---|---|
| Qwen3-Coder-30B-A3B | 11 → **18 / 28** (+7, none lost) | 52 % → 81 % | 1.56 | 42 / 64 (66 %) | 43 s |
| Devstral-Small-2-24B | 8 → **18 / 28** (+12, 2 lost) | 15 % → 67 % | 1.33 | 35 / 67 (52 %) | 94 s |

Per requirement, v1 → v2: exact McNemar p = 0.016 (Qwen3-Coder) and 0.013 (Devstral). Together the two models
verify 21 of the 28 requirements; 15 are verified by both.

Failed attempts by primary cause (`failure_causes`):

| Cause | Qwen3-Coder v1 → v2 | Devstral v1 → v2 |
|---|---|---|
| Dispatch call on the wrong object or a passive component | 23 → **0** | 42 → **0** |
| Namespace-qualified method definition (agent bug) | 8 → **0** | 0 → 0 |
| Answer missing a block | 5 → 1 | 0 → 0 |
| Other compile errors (invented enum values, include paths, port APIs) | 1 → 14 | 13 → 20 |
| F´ assertion in the component (test broke a precondition) | 6 → 10 | 1 → 6 |
| Wrong expected value | 7 → 6 | 6 → 9 |
| Reused an existing name / other policy | 5 → 8 | 0 → 1 |
| `-Werror`: C-style cast or deprecated API | 0 → 1 | 4 → 0 |
| **Total failed attempts** | **55 → 40** | **66 → 36** |

The causes v2 targeted are gone. What remains is the models' knowledge of the F´ API (enum values such as
`Fw::ParamValid::PARAM_VALID`, include paths such as `Fw/Buffer.hpp`, port helpers) and of each component's
preconditions. These failures now appear later in the pipeline, which is why some counts rise: requirements
that used to stop at the dispatch error now reach the build of their real content. Next steps for the agent,
in the same spirit: resolve unknown includes to the real header by file name, and add the enumerators of an
unknown enum value to the hints.

**Relevance:** an AI pre-review of the 36 verified tests (`agent-v2/ai-prereview.md`, to be confirmed by an
engineer on the review sheets) finds 30 relevant and 6 partial (one case of a multi-case requirement), none
irrelevant. The generated tests are in `agent-v2/*.patch` (`git am` on F´ v4.4.1).

## Reproduce

```bash
python scripts/build_kaggle_notebook.py kaggle/01_benchmark.py --standalone \
    --set 'STAGES=["serving", "agent"]' --out 01_benchmark_rerun.ipynb   # at bf66c9d
uv run oge agent report docs/results/bench/run3-2026-10-28/agent-v2/qwen3-coder-30b-a3b__llamacpp.jsonl
```

`*.kaggle-summary.json` are the summaries written on Kaggle; `*.summary.json` and `*.review.md` were regenerated
with `oge agent report` (same numbers, plus `failure_causes`).
