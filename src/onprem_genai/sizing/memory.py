"""GPU memory model: weights + KV cache + linear-attention state + runtime overhead."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from onprem_genai.sizing.specs import IncompleteSpecError, KvFormat, ModelSpec, WeightFormat

GB = 1e9


def weight_bytes(spec: ModelSpec, fmt: WeightFormat, artifact_format: str | None = None) -> tuple[float, str]:
    """Weight memory. A measured artifact of the requested format wins over the bits-per-weight estimate."""
    wanted = artifact_format or fmt.key
    for art in spec.artifacts:
        if art.format == wanted:
            return art.bytes, f"measured artifact ({art.source})"
    spec.require("params_total")
    assert spec.params_total is not None
    return (
        spec.params_total * fmt.bits_per_weight / 8,
        f"estimate: params x {fmt.bits_per_weight} bpw ({fmt.source})",
    )


def kv_bytes_per_token(spec: ModelSpec, kv: KvFormat) -> float:
    """KV-cache bytes per cached token, summed over all softmax-attention layers."""
    spec.require("full_attn_layers")
    assert spec.full_attn_layers is not None
    if spec.mla_kv_dim is not None:
        return spec.full_attn_layers * spec.mla_kv_dim * kv.bytes_per_element
    spec.require("kv_heads", "head_dim")
    assert spec.kv_heads is not None and spec.head_dim is not None
    return spec.full_attn_layers * 2 * spec.kv_heads * spec.head_dim * kv.bytes_per_element


def linear_state_bytes_per_sequence(spec: ModelSpec, activation_bytes: float = 2.0) -> float:
    """Fixed-size recurrent state of linear-attention (Gated DeltaNet) layers, per active sequence.

    Per layer: SSM state ``[v_heads, k_dim, v_dim]`` (stored in ``linear_state_bytes`` precision) plus the
    causal convolution state ``(conv_kernel - 1) x (2 * k_heads * k_dim + v_heads * v_dim)`` in activation
    precision.
    """
    if spec.linear_attn_layers == 0:
        return 0.0
    if not (spec.linear_v_heads and spec.linear_k_dim and spec.linear_v_dim):
        raise IncompleteSpecError(f"{spec.key}: linear-attention head dimensions not verified")
    ssm = spec.linear_v_heads * spec.linear_k_dim * spec.linear_v_dim * spec.linear_state_bytes
    conv_channels = 2 * spec.linear_k_heads * spec.linear_k_dim + spec.linear_v_heads * spec.linear_v_dim
    conv = max(spec.linear_conv_kernel - 1, 0) * conv_channels * activation_bytes
    return spec.linear_attn_layers * (ssm + conv)


@dataclass(frozen=True)
class MemoryEstimate:
    weights_gb: float
    kv_cache_gb: float
    linear_state_gb: float
    overhead_gb: float
    total_gb: float
    per_gpu_gb: float
    gpu_memory_gb: float
    n_gpus: int
    fits: bool
    weights_source: str
    kv_bytes_per_token: float

    def as_dict(self) -> dict[str, float | int | bool | str]:
        return asdict(self)


def estimate_memory(
    spec: ModelSpec,
    weight_fmt: WeightFormat,
    kv_fmt: KvFormat,
    *,
    cached_tokens: int,
    n_sequences: int,
    n_gpus: int,
    gpu_memory_gb: float,
    overhead_gb_per_gpu: float = 1.0,
    usable_fraction: float = 0.92,
    artifact_format: str | None = None,
) -> MemoryEstimate:
    """Memory needed to serve ``n_sequences`` concurrent sequences holding ``cached_tokens`` tokens in total.

    ``overhead_gb_per_gpu`` covers CUDA context, workspace and activation buffers; it is calibrated from
    measurements (see :mod:`onprem_genai.sizing.calibration`). ``usable_fraction`` reserves headroom against
    fragmentation, mirroring ``--gpu-memory-utilization`` in vLLM.
    """
    w_bytes, w_source = weight_bytes(spec, weight_fmt, artifact_format)
    kv_tok = kv_bytes_per_token(spec, kv_fmt)
    kv = kv_tok * cached_tokens
    lin = linear_state_bytes_per_sequence(spec) * n_sequences
    overhead = overhead_gb_per_gpu * GB * n_gpus
    total = w_bytes + kv + lin + overhead
    per_gpu = total / n_gpus
    return MemoryEstimate(
        weights_gb=w_bytes / GB,
        kv_cache_gb=kv / GB,
        linear_state_gb=lin / GB,
        overhead_gb=overhead / GB,
        total_gb=total / GB,
        per_gpu_gb=per_gpu / GB,
        gpu_memory_gb=gpu_memory_gb,
        n_gpus=n_gpus,
        fits=per_gpu <= gpu_memory_gb * GB * usable_fraction,
        weights_source=w_source,
        kv_bytes_per_token=kv_tok,
    )


def max_cached_tokens(
    spec: ModelSpec,
    weight_fmt: WeightFormat,
    kv_fmt: KvFormat,
    *,
    n_sequences: int,
    n_gpus: int,
    gpu_memory_gb: float,
    overhead_gb_per_gpu: float = 1.0,
    usable_fraction: float = 0.92,
    artifact_format: str | None = None,
) -> int:
    """Largest total KV-cache capacity (tokens) that fits after weights, state and overhead."""
    w_bytes, _ = weight_bytes(spec, weight_fmt, artifact_format)
    budget = gpu_memory_gb * GB * usable_fraction * n_gpus
    free = budget - w_bytes - overhead_gb_per_gpu * GB * n_gpus
    free -= linear_state_bytes_per_sequence(spec) * n_sequences
    if free <= 0:
        return 0
    return int(free // kv_bytes_per_token(spec, kv_fmt))
