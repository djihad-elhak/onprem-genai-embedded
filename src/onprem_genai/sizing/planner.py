"""Capacity planning: how many GPUs a team needs for a given model, quantization and workload.

Method (per candidate deployment = GPU type x GPUs per replica x parallelism):

1. Memory bounds the batch: largest number of concurrent sequences ``B_mem`` whose KV cache and recurrent
   state fit next to the weights.
2. The latency SLO bounds it further: ``B*`` is the largest batch whose per-sequence decode speed stays above
   ``min_decode_tps_per_sequence``.
3. Demand via Little's law: concurrent sequences ``C = sum(lambda_i * service_time_i)``; prefill load
   ``U = sum(lambda_i * uncached_prompt_i / prefill_tps)`` (fraction of one replica's time).
4. Replicas ``R >= headroom * (C / B* + U)``, i.e. each replica's decode slots are reduced by the time it
   spends on prefill.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from importlib import resources
from typing import Any

import yaml
from pydantic import BaseModel

from onprem_genai.sizing.memory import GB, kv_bytes_per_token, linear_state_bytes_per_sequence, weight_bytes
from onprem_genai.sizing.performance import Calibration, Parallelism, estimate_decode, estimate_prefill_tps
from onprem_genai.sizing.specs import DATA_PACKAGE, GpuSpec, KvFormat, ModelSpec, WeightFormat


class RequestClass(BaseModel):
    name: str
    requests_per_engineer_hour: float
    prompt_tokens: int
    output_tokens: int
    cached_prefix_fraction: float = 0.0


class Scenario(BaseModel):
    key: str
    description: str
    request_classes: list[RequestClass]
    peak_active_fraction: float
    min_decode_tps_per_sequence: float
    headroom: float


def load_scenarios() -> dict[str, Scenario]:
    raw = yaml.safe_load(resources.files(DATA_PACKAGE).joinpath("workloads.yaml").read_text(encoding="utf-8"))
    d = raw["defaults"]
    return {k: Scenario(key=k, **{**d, **v}) for k, v in raw["scenarios"].items()}


@dataclass(frozen=True)
class Plan:
    gpu: str
    gpus_per_replica: int
    parallelism: str
    feasible: bool
    reason: str
    replicas: int
    total_gpus: int
    batch_per_replica: int
    batch_memory_limit: int
    per_sequence_tps: float
    concurrent_sequences: float
    prefill_load: float
    ttft_s: dict[str, float]
    weights_gb_per_gpu: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mean_resident_tokens(scenario: Scenario) -> int:
    rates = [rc.requests_per_engineer_hour for rc in scenario.request_classes]
    tokens = [rc.prompt_tokens + rc.output_tokens for rc in scenario.request_classes]
    return int(sum(r * t for r, t in zip(rates, tokens, strict=True)) / sum(rates))


def plan_deployment(
    spec: ModelSpec,
    weight_fmt: WeightFormat,
    kv_fmt: KvFormat,
    gpu: GpuSpec,
    scenario: Scenario,
    *,
    engineers: int,
    gpus_per_replica: int,
    parallelism: Parallelism,
    calib: Calibration,
    overhead_gb_per_gpu: float = 1.0,
    usable_fraction: float = 0.92,
    max_batch: int = 256,
    artifact_format: str | None = None,
) -> Plan:
    def infeasible(reason: str, b_mem: int = 0) -> Plan:
        return Plan(
            gpu.key,
            gpus_per_replica,
            parallelism.value,
            False,
            reason,
            0,
            0,
            0,
            b_mem,
            0.0,
            0.0,
            0.0,
            {},
            0.0,
        )

    if weight_fmt.key == "bf16" and not gpu.supports_bf16:
        return infeasible("BF16 not supported on this GPU")
    if (weight_fmt.key == "fp8" or kv_fmt.key == "fp8") and not gpu.supports_fp8:
        return infeasible("FP8 not supported on this GPU")

    w_bytes, _ = weight_bytes(spec, weight_fmt, artifact_format)
    budget = (
        gpu.memory_gb * GB * usable_fraction * gpus_per_replica - overhead_gb_per_gpu * GB * gpus_per_replica
    )
    free = budget - w_bytes
    if free <= 0:
        return infeasible("weights do not fit")
    resident = _mean_resident_tokens(scenario)
    per_seq_bytes = resident * kv_bytes_per_token(spec, kv_fmt) + linear_state_bytes_per_sequence(spec)
    b_mem = min(int(free // per_seq_bytes), max_batch)
    if b_mem < 1:
        return infeasible("no room for a single sequence's KV cache")

    # Largest batch meeting the per-sequence speed SLO (decode speed decreases monotonically with batch).
    best_b, best_v = 0, 0.0
    for b in range(1, b_mem + 1):
        est = estimate_decode(
            spec,
            weight_fmt,
            kv_fmt,
            gpu,
            n_gpus=gpus_per_replica,
            parallelism=parallelism,
            batch=b,
            avg_context=resident,
            calib=calib,
            artifact_format=artifact_format,
        )
        if est.per_sequence_tps < scenario.min_decode_tps_per_sequence:
            break
        best_b, best_v = b, est.per_sequence_tps
    if best_b == 0:
        return infeasible(f"single-stream decode below {scenario.min_decode_tps_per_sequence} tok/s", b_mem)

    active = engineers * scenario.peak_active_fraction
    concurrent, prefill_load, ttft = 0.0, 0.0, {}
    for rc in scenario.request_classes:
        lam = active * rc.requests_per_engineer_hour / 3600.0
        uncached = rc.prompt_tokens * (1.0 - rc.cached_prefix_fraction)
        p_tps = estimate_prefill_tps(
            spec,
            gpu,
            n_gpus=gpus_per_replica,
            parallelism=parallelism,
            prompt_tokens=rc.prompt_tokens,
            calib=calib,
        )
        t_first = uncached / p_tps
        ttft[rc.name] = round(t_first, 3)
        concurrent += lam * (t_first + rc.output_tokens / best_v)
        prefill_load += lam * t_first
    replicas = max(1, math.ceil(scenario.headroom * (concurrent / best_b + prefill_load)))
    return Plan(
        gpu=gpu.key,
        gpus_per_replica=gpus_per_replica,
        parallelism=parallelism.value,
        feasible=True,
        reason="ok",
        replicas=replicas,
        total_gpus=replicas * gpus_per_replica,
        batch_per_replica=best_b,
        batch_memory_limit=b_mem,
        per_sequence_tps=round(best_v, 1),
        concurrent_sequences=round(concurrent, 2),
        prefill_load=round(prefill_load, 3),
        ttft_s=ttft,
        weights_gb_per_gpu=round(w_bytes / GB / gpus_per_replica, 2),
    )


def best_plan_per_gpu(
    spec: ModelSpec,
    weight_fmt: WeightFormat,
    kv_fmt: KvFormat,
    gpus: dict[str, GpuSpec],
    scenario: Scenario,
    *,
    engineers: int,
    calib: Calibration,
    replica_sizes: tuple[int, ...] = (1, 2, 4, 8),
    overhead_gb_per_gpu: float = 1.0,
    artifact_format: str | None = None,
) -> list[Plan]:
    """For each GPU type, the feasible tensor-parallel replica size that minimises the total GPU count."""
    out: list[Plan] = []
    for gpu in gpus.values():
        candidates = [
            plan_deployment(
                spec,
                weight_fmt,
                kv_fmt,
                gpu,
                scenario,
                engineers=engineers,
                gpus_per_replica=n,
                parallelism=Parallelism.TENSOR,
                calib=calib,
                overhead_gb_per_gpu=overhead_gb_per_gpu,
                artifact_format=artifact_format,
            )
            for n in replica_sizes
        ]
        feasible = [p for p in candidates if p.feasible]
        if feasible:
            out.append(min(feasible, key=lambda p: (p.total_gpus, p.gpus_per_replica)))
        else:
            out.append(candidates[-1])
    return out


def min_gpus_for_weights(
    spec: ModelSpec,
    weight_fmt: WeightFormat,
    gpu: GpuSpec,
    *,
    overhead_gb_per_gpu: float = 1.0,
    usable_fraction: float = 0.92,
    artifact_format: str | None = None,
) -> int:
    """Lower bound on GPUs needed just to hold the weights (used when the KV layout is not yet verified)."""
    w_bytes, _ = weight_bytes(spec, weight_fmt, artifact_format)
    per_gpu = gpu.memory_gb * GB * usable_fraction - overhead_gb_per_gpu * GB
    return math.ceil(w_bytes / per_gpu)


def max_request_rate(
    spec: ModelSpec,
    weight_fmt: WeightFormat,
    kv_fmt: KvFormat,
    gpu: GpuSpec,
    scenario: Scenario,
    *,
    gpus_per_replica: int,
    parallelism: Parallelism,
    calib: Calibration,
    artifact_format: str | None = None,
    max_engineers: int = 100_000,
) -> tuple[float, Plan | None]:
    """Largest request rate (requests/s, all classes) one replica serves within the SLO, without headroom.

    Comparable with a load test: every engineer counts as active and no capacity margin is kept.
    """
    sc = scenario.model_copy(update={"headroom": 1.0, "peak_active_fraction": 1.0})
    per_engineer = sum(rc.requests_per_engineer_hour for rc in sc.request_classes) / 3600.0

    def plan(n: int) -> Plan:
        return plan_deployment(
            spec,
            weight_fmt,
            kv_fmt,
            gpu,
            sc,
            engineers=n,
            gpus_per_replica=gpus_per_replica,
            parallelism=parallelism,
            calib=calib,
            artifact_format=artifact_format,
        )

    first = plan(1)
    if not first.feasible or first.replicas > 1:
        return 0.0, first if not first.feasible else None
    lo, hi = 1, 2
    while hi <= max_engineers and plan(hi).replicas == 1:  # replicas grows monotonically with the team
        lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if plan(mid).replicas == 1 else (lo, mid)
    return lo * per_engineer, plan(lo)
