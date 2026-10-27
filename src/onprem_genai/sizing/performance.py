"""Roofline-style throughput model for LLM serving, calibrated against measurements.

Decode (token generation) is usually memory-bandwidth bound: every step streams the touched weights once
(shared by the whole batch) plus each sequence's KV cache and recurrent state. Prefill (prompt processing) is
compute bound. Two efficiency factors map peak datasheet numbers to what an engine actually achieves; they
are fitted on measured runs (:mod:`onprem_genai.sizing.calibration`), never assumed silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onprem_genai.sizing.memory import kv_bytes_per_token, linear_state_bytes_per_sequence, weight_bytes
from onprem_genai.sizing.specs import GpuSpec, KvFormat, ModelSpec, WeightFormat


class Parallelism(StrEnum):
    TENSOR = "tensor"  # vLLM/SGLang tensor parallel: GPUs work on every layer concurrently
    LAYER = "layer"  # llama.cpp default split: layers distributed, GPUs work one after another


@dataclass(frozen=True)
class Calibration:
    decode_bw_efficiency: float = 0.6
    prefill_compute_efficiency: float = 0.35
    tp_efficiency: float = 0.85
    source: str = "uncalibrated defaults"


@dataclass(frozen=True)
class DecodeEstimate:
    batch: int
    avg_context: int
    per_sequence_tps: float
    aggregate_tps: float
    step_ms: float
    bound: str
    weight_bytes_per_step: float
    kv_bytes_per_step: float


def _scale(n_gpus: int, parallelism: Parallelism, calib: Calibration) -> float:
    if n_gpus <= 1 or parallelism is Parallelism.LAYER:
        return 1.0
    return n_gpus * calib.tp_efficiency


def touched_weight_bytes(spec: ModelSpec, total_weight_bytes: float, batch: int) -> float:
    """Weight bytes read in one decode step.

    For MoE models each token activates ``k`` of ``E`` experts per layer; with a batch of ``B`` independent
    tokens the expected fraction of distinct experts touched is ``1 - (1 - k/E)^B``. Dense weights (attention,
    shared experts, embeddings) are always read.
    """
    if not spec.is_moe:
        return total_weight_bytes
    assert spec.num_experts is not None and spec.experts_per_token is not None
    expert_params = spec.expert_params
    if expert_params is None or not spec.params_total:
        # No per-expert breakdown available: fall back to the active-parameter share (batch-independent).
        if spec.params_active and spec.params_total:
            return total_weight_bytes * spec.params_active / spec.params_total
        return total_weight_bytes
    expert_share = min(expert_params / spec.params_total, 1.0)
    expert_bytes = total_weight_bytes * expert_share
    dense_bytes = total_weight_bytes - expert_bytes
    touched = 1.0 - (1.0 - spec.experts_per_token / spec.num_experts) ** max(batch, 1)
    return dense_bytes + expert_bytes * touched


def flops_per_token(spec: ModelSpec, context: int) -> float:
    """Forward FLOPs for one token: 2 x active params + softmax-attention score/value products."""
    spec.require("params_active")
    assert spec.params_active is not None
    attn = 0.0
    if spec.full_attn_layers and spec.num_attention_heads and spec.head_dim:
        attn = 4.0 * context * spec.num_attention_heads * spec.head_dim * spec.full_attn_layers
    return 2.0 * spec.params_active + attn


def estimate_decode(
    spec: ModelSpec,
    weight_fmt: WeightFormat,
    kv_fmt: KvFormat,
    gpu: GpuSpec,
    *,
    n_gpus: int,
    parallelism: Parallelism,
    batch: int,
    avg_context: int,
    calib: Calibration,
    artifact_format: str | None = None,
) -> DecodeEstimate:
    w_total, _ = weight_bytes(spec, weight_fmt, artifact_format)
    w_step = touched_weight_bytes(spec, w_total, batch)
    kv_step = batch * avg_context * kv_bytes_per_token(spec, kv_fmt)
    state_step = batch * 2.0 * linear_state_bytes_per_sequence(spec)  # read + write
    scale = _scale(n_gpus, parallelism, calib)
    mem_time = (w_step + kv_step + state_step) / (
        gpu.bandwidth_gbs * 1e9 * calib.decode_bw_efficiency * scale
    )
    compute = gpu.fp16_dense_tflops * 1e12 * calib.prefill_compute_efficiency * scale
    compute_time = batch * flops_per_token(spec, avg_context) / compute
    step = max(mem_time, compute_time)
    return DecodeEstimate(
        batch=batch,
        avg_context=avg_context,
        per_sequence_tps=1.0 / step,
        aggregate_tps=batch / step,
        step_ms=step * 1e3,
        bound="memory" if mem_time >= compute_time else "compute",
        weight_bytes_per_step=w_step,
        kv_bytes_per_step=kv_step,
    )


def estimate_prefill_tps(
    spec: ModelSpec,
    gpu: GpuSpec,
    *,
    n_gpus: int,
    parallelism: Parallelism,
    prompt_tokens: int,
    calib: Calibration,
) -> float:
    """Prompt-processing throughput (tokens/s) for a prompt of ``prompt_tokens`` tokens."""
    scale = _scale(n_gpus, parallelism, calib)
    compute = gpu.fp16_dense_tflops * 1e12 * calib.prefill_compute_efficiency * scale
    return compute / flops_per_token(spec, max(prompt_tokens // 2, 1))
