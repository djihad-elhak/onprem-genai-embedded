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
    """Median implied efficiencies: dense and MoE models separately (each falls back to the other class)."""
    dec: dict[bool, list[float]] = {False: [], True: []}
    pre: dict[bool, list[float]] = {False: [], True: []}
    for m in measurements:
        spec, wf, gpu = specs[m.model_key], weight_formats[m.weight_format], gpus[m.gpu_key]
        moe = bool(spec.num_experts)
        if m.decode_tps_single:
            dec[moe].append(implied_decode_efficiency(m, spec, wf, kv, gpu, tp_efficiency))
        if m.prefill_tps and m.prefill_prompt_tokens:
            pre[moe].append(implied_prefill_efficiency(m, spec, gpu, tp_efficiency))
    if not dec[False] and not dec[True]:
        raise ValueError("no decode measurements to calibrate on")

    def med(xs: list[float], other: list[float], default: float) -> float:
        return statistics.median(xs) if xs else (statistics.median(other) if other else default)

    defaults = Calibration()
    return Calibration(
        decode_bw_efficiency=med(dec[False], dec[True], defaults.decode_bw_efficiency),
        prefill_compute_efficiency=med(pre[False], pre[True], defaults.prefill_compute_efficiency),
        tp_efficiency=tp_efficiency,
        source=(
            f"median over {len(dec[False])} dense + {len(dec[True])} MoE decode, "
            f"{len(pre[False])} dense + {len(pre[True])} MoE prefill measurements"
        ),
        moe_decode_bw_efficiency=med(dec[True], dec[False], defaults.decode_bw_efficiency),
        moe_prefill_compute_efficiency=med(pre[True], pre[False], defaults.prefill_compute_efficiency),
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


_VLLM_FORMATS = {"auto_awq": "awq_int4_g128", "awq": "awq_int4_g128", "auto_gptq": "gptq_int4_g128"}


def measurements_from_probe(
    probe: dict[str, Any], gpu_key: str = "t4", engine: str = "llama.cpp"
) -> list[Measurement]:
    """Single-stream decode and long-prompt prefill measured by the probe, for one engine.

    llama.cpp splits layers across the GPUs (they work one after another): ``Parallelism.LAYER``, weights =
    GGUF file size, 16k-context single-slot launch. vLLM runs with tensor parallelism: ``Parallelism.TENSOR``,
    weights = the loaded size it logs per rank; runs forced into eager mode are skipped (no CUDA graphs: not
    the configuration anyone would deploy).
    """
    out: list[Measurement] = []
    for run in probe.get("runs", []):
        if run.get("engine") != engine or run.get("status") != "done":
            continue
        if engine == "llama.cpp":
            launch = next((x for x in run.get("launches", []) if x.get("label") == "single_16k"), None)
            if not launch or not launch.get("loaded") or not launch.get("single_stream"):
                continue
            single, prefill = launch["single_stream"], launch.get("prefill") or {}
            peak = list(launch.get("vram_peak_mib") or [])
            fmt, par = "q4_k_m", Parallelism.LAYER
            w_bytes = run["file_size_gb"] * 1e9 if run.get("file_size_gb") else None
        elif engine == "vllm":
            if run.get("enforce_eager") or not run.get("single_stream"):
                continue
            info = run.get("log_info") or {}
            fmt = _VLLM_FORMATS.get(str(info.get("quantization", "")))
            if fmt is None:
                continue
            single, prefill = run["single_stream"], run.get("prefill") or {}
            peak, par = list(run.get("vram_peak_mib") or []), Parallelism.TENSOR
            per_rank = info.get("weights_gib_per_rank")
            w_bytes = per_rank * (len(peak) or 1) * 2**30 if per_rank else None
        else:
            raise ValueError(f"unknown engine {engine!r}")
        out.append(
            Measurement(
                engine=engine,
                model_key=run["model_key"],
                weight_format=fmt,
                gpu_key=gpu_key,
                n_gpus=len(peak) or 1,
                parallelism=par,
                decode_tps_single=single.get("decode_tps"),
                decode_context=int(single.get("prompt_tokens", 0) + single.get("completion_tokens", 0) / 2),
                prefill_tps=prefill.get("prefill_tps"),
                prefill_prompt_tokens=prefill.get("prompt_tokens"),
                weights_bytes=w_bytes,
                vram_peak_mib=peak,
                label=f"{run['model_key']} {fmt} {engine}",
            )
        )
    return out
