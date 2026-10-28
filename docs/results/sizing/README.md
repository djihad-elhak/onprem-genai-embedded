# Sizing calibration and team tables

Produced by `oge sizing calibrate` (from the probe) and `oge sizing report` (team tables). Architectures and
exact parameter counts come from the official `config.json` / `model.safetensors.index.json` of each model
(`../bench/run2-2026-10-28/model_configs`, imported with `oge sizing import-config`).

## Calibration (`calibration_*_t4.json`)

The performance model is a roofline: decode is bounded by the bytes read per step (weights touched + KV cache
+ recurrent state) at a fraction of peak bandwidth, prefill by FLOPs at a fraction of peak FP16. The fractions
are fitted on probe run 2 (single stream, 2× T4). Dense and MoE models are fitted separately because their
achieved fractions differ widely on the same engine:

| Engine (2× T4) | Decode, dense / MoE (of peak bandwidth) | Prefill, dense / MoE (of peak FP16) | Measurements |
|---|---|---|---|
| llama.cpp, layer split, Q4_K_M | 0.771 / 0.590 | 0.508 / 0.202 | 2 dense + 2 MoE |
| vLLM 0.32, tensor parallel 2, AWQ | – / 0.374 | – / 0.030 | 1 MoE (Qwen3-Coder) |

vLLM's numbers reflect Turing: no Marlin kernels for AWQ and no FlashAttention 2 on SM 7.5. They are not a
property of vLLM on Ampere or Hopper GPUs.

### Validation

**Leave-one-model-out** (llama.cpp): each model is predicted with fractions fitted on the other models of the
same class (`calibration_llamacpp_t4.validation.json`).

| Model | Decode measured → predicted | Prefill measured → predicted |
|---|---|---|
| Qwen3.8-27B (dense) | 13.9 → 13.7 tok/s (−1.5 %) | 550 → 584 tok/s (+6.2 %) |
| Devstral-Small-2-24B (dense) | 15.9 → 16.1 tok/s (+1.5 %) | 649 → 611 tok/s (−5.8 %) |
| Qwen3-Coder-30B-A3B (MoE) | 81.9 → 90.6 tok/s (+10.6 %) | 1,445 → 809 tok/s (−44 %) |
| Qwen3.6-35B-A3B (MoE, hybrid attention) | 60.9 → 55.1 tok/s (−9.6 %) | 1,326 → 2,368 tok/s (+79 %) |

Decode is predicted within ±11 %. MoE prefill is not: the two MoE models differ in attention (Qwen3.6 has
linear-attention layers), and one MoE model is not enough to predict the other.

**Independent run** (benchmark run 3, chat profile, one stream, ≈ 2.8k-token context, a context the calibration
never saw):

| Model (llama.cpp) | Decode measured → predicted | Time to first token measured → predicted |
|---|---|---|
| Qwen3-Coder-30B-A3B | 73.6 → 76.7 tok/s (+4 %) | 2.32 → 1.48 s (−36 %) |
| Devstral-Small-2-24B | 15.2 → 15.6 tok/s (+3 %) | 5.04 → 4.01 s (−21 %) |

**Capacity of one 2× T4 server, chat scenario** (3,000-token prompts, 400-token answers, ≥ 20 tok/s per user):

| Deployment | Planner: max requests/s | Measured (run 3) | |
|---|---|---|---|
| Qwen3-Coder, llama.cpp | 0.187 (6 concurrent) | 0.174 at 4 streams, 23 tok/s per user (4 server slots) | +7 % |
| Devstral, llama.cpp | infeasible: 15.6 tok/s single stream < 20 | 15.2 tok/s single stream | consistent |
| Qwen3-Coder, vLLM | 0.090 | 0.185 at 4 streams (27 tok/s per user); at 8 streams 14 tok/s per user, below the SLO | −51 % |

The planner is accurate on llama.cpp. On vLLM it is conservative: its prefill fraction was fitted on a
13k-token prompt, and on Turing vLLM's prefill is much slower on long prompts than on 3k-token ones (≈ 280 vs
≈ 1,100 tok/s). Time to first token is under-predicted by 20–35 % (request handling and chat templating are not
modelled).

## Team tables (`team_tables.md`)

`oge sizing report -m qwen3-coder-30b-a3b -m devstral-small-2-24b -g l4 -g l40s -g a100-80g-sxm -g h100-sxm
-g h200 --calibration calibration_llamacpp_t4.json`: total GPUs for 25 / 100 / 400 engineers and three workload
scenarios, 4-bit weights, tensor parallelism inside a replica, assumptions of
`src/onprem_genai/sizing/data/workloads.yaml` (60 % of the team active at the peak hour, 20 tok/s per user, 1.25
headroom).

**What these tables assume:** the efficiencies measured on T4 with llama.cpp carry over to other GPUs and to
the production engine. That holds only to first order; kernels differ by GPU generation. Before any purchase,
the probe notebook is re-run on the candidate GPU and the tables are regenerated from that calibration, which is
the procedure the tables were built to support.

## Reproduce

```bash
P=docs/results/probe/run2-2026-10-28.json; C=docs/results/sizing
uv run oge sizing calibrate --probe $P --out $C/calibration_llamacpp_t4.json
uv run oge sizing calibrate --probe $P --engine vllm --out $C/calibration_vllm_t4.json
uv run oge sizing capacity qwen3-coder-30b-a3b --parallelism layer --weights-bytes 18.56e9 \
    --calibration $C/calibration_llamacpp_t4.json                          # 0.187 requests/s
uv run oge sizing capacity qwen3-coder-30b-a3b --parallelism tensor --weights awq_int4_g128 \
    --weights-bytes 17.07e9 --calibration $C/calibration_vllm_t4.json      # 0.090 requests/s
uv run oge sizing report -m qwen3-coder-30b-a3b -m devstral-small-2-24b -g l4 -g l40s -g a100-80g-sxm \
    -g h100-sxm -g h200 --calibration $C/calibration_llamacpp_t4.json --out $C/team_tables.md
```
