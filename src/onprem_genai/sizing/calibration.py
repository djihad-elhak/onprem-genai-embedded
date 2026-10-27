"""Fit the performance-model efficiencies on measured runs and report prediction error.

Measurements come from the Kaggle notebooks (probe / serving benchmark). Validation is leave-one-model-out:
the efficiencies used to predict a model are fitted on the *other* models only, so the reported error reflects
how well the calculator generalises to a model it has not seen.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from onprem_genai.sizing.memory import kv_bytes_per_token, linear_state_bytes_per_sequence, weight_bytes
from onprem_genai.sizing.performance import (
    Calibration,
    Parallelism,
    estimate_decode,
    estimate_prefill_tps,
    flops_per_token,
    touched_weight_bytes,
)
from onprem_genai.sizing.specs import Artifact, GpuSpec, KvFormat, ModelSpec, WeightFormat


@dataclass
class Measurement:
    engine: str
    model_key: str
    weight_format: str
    gpu_key: str
    n_gpus: int
    parallelism: Parallelism
    decode_tps_single: float | None
    decode_context: int
    prefill_tps: float | None
    prefill_prompt_tokens: int | None
    weights_bytes: float | None = None
    vram_peak_mib: list[int] = field(default_factory=list)
    label: str = ""


def implied_decode_efficiency(
    m: Measurement, spec: ModelSpec, wf: WeightFormat, kv: KvFormat, gpu: GpuSpec, tp_eff: float
) -> float:
    """Fraction of peak bandwidth needed to explain the measured single-stream decode speed."""
    assert m.decode_tps_single
    w_total = m.weights_bytes or weight_bytes(spec, wf)[0]
    step_bytes = (
        touched_weight_bytes(spec, w_total, 1)
        + m.decode_context * kv_bytes_per_token(spec, kv)
        + 2 * linear_state_bytes_per_sequence(spec)
    )
    scale = m.n_gpus * tp_eff if (m.parallelism is Parallelism.TENSOR and m.n_gpus > 1) else 1.0
    return m.decode_tps_single * step_bytes / (gpu.bandwidth_gbs * 1e9 * scale)


def implied_prefill_efficiency(m: Measurement, spec: ModelSpec, gpu: GpuSpec, tp_eff: float) -> float:
    assert m.prefill_tps and m.prefill_prompt_tokens
    scale = m.n_gpus * tp_eff if (m.parallelism is Parallelism.TENSOR and m.n_gpus > 1) else 1.0
    flops = flops_per_token(spec, m.prefill_prompt_tokens // 2)
    return m.prefill_tps * flops / (gpu.fp16_dense_tflops * 1e12 * scale)


def fit(
    measurements: list[Measurement],
    specs: dict[str, ModelSpec],
    weight_formats: dict[str, WeightFormat],
    kv: KvFormat,
    gpus: dict[str, GpuSpec],
    tp_efficiency: float = 0.85,
) -> Calibration:
    dec, pre = [], []
    for m in measurements:
        spec, wf, gpu = specs[m.model_key], weight_formats[m.weight_format], gpus[m.gpu_key]
        if m.decode_tps_single:
            dec.append(implied_decode_efficiency(m, spec, wf, kv, gpu, tp_efficiency))
        if m.prefill_tps and m.prefill_prompt_tokens:
            pre.append(implied_prefill_efficiency(m, spec, gpu, tp_efficiency))
    if not dec:
        raise ValueError("no decode measurements to calibrate on")
    return Calibration(
        decode_bw_efficiency=statistics.median(dec),
        prefill_compute_efficiency=statistics.median(pre)
        if pre
        else Calibration().prefill_compute_efficiency,
        tp_efficiency=tp_efficiency,
        source=f"median over {len(dec)} decode / {len(pre)} prefill measurements",
    )


def leave_one_model_out(
    measurements: list[Measurement],
    specs: dict[str, ModelSpec],
    weight_formats: dict[str, WeightFormat],
    kv: KvFormat,
    gpus: dict[str, GpuSpec],
    tp_efficiency: float = 0.85,
) -> list[dict[str, Any]]:
    """Predict each measurement with efficiencies fitted on the other models (same engine)."""
    rows = []
    for m in measurements:
        train = [o for o in measurements if o.model_key != m.model_key and o.engine == m.engine]
        if not train or not m.decode_tps_single:
            continue
        calib = fit(train, specs, weight_formats, kv, gpus, tp_efficiency)
        spec = specs[m.model_key]
        if m.weights_bytes:
            spec = spec.model_copy(
                update={
                    "artifacts": [
                        *spec.artifacts,
                        Artifact(format=m.weight_format, bytes=m.weights_bytes, source="measured file size"),
                    ]
                }
            )
        pred = estimate_decode(
            spec,
            weight_formats[m.weight_format],
            kv,
            gpus[m.gpu_key],
            n_gpus=m.n_gpus,
            parallelism=m.parallelism,
            batch=1,
            avg_context=m.decode_context,
            calib=calib,
        )
        row: dict[str, Any] = {
            "engine": m.engine,
            "model": m.model_key,
            "measured_decode_tps": m.decode_tps_single,
            "predicted_decode_tps": round(pred.per_sequence_tps, 2),
            "decode_error_pct": round(
                100 * (pred.per_sequence_tps - m.decode_tps_single) / m.decode_tps_single, 1
            ),
        }
        if m.prefill_tps and m.prefill_prompt_tokens:
            p = estimate_prefill_tps(
                spec,
                gpus[m.gpu_key],
                n_gpus=m.n_gpus,
                parallelism=m.parallelism,
                prompt_tokens=m.prefill_prompt_tokens,
                calib=calib,
            )
            row.update(
                measured_prefill_tps=m.prefill_tps,
                predicted_prefill_tps=round(p, 1),
                prefill_error_pct=round(100 * (p - m.prefill_tps) / m.prefill_tps, 1),
            )
        rows.append(row)
    return rows
