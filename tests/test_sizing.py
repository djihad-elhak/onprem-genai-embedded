from __future__ import annotations

import json
from pathlib import Path

import pytest

from onprem_genai.sizing.calibration import Measurement, fit, leave_one_model_out, measurements_from_probe
from onprem_genai.sizing.memory import (
    estimate_memory,
    kv_bytes_per_token,
    linear_state_bytes_per_sequence,
    max_cached_tokens,
    weight_bytes,
)
from onprem_genai.sizing.performance import (
    Calibration,
    Parallelism,
    estimate_decode,
    touched_weight_bytes,
)
from onprem_genai.sizing.planner import (
    load_scenarios,
    max_request_rate,
    min_gpus_for_weights,
    plan_deployment,
)
from onprem_genai.sizing.specs import (
    IncompleteSpecError,
    ModelSpec,
    load_formats,
    load_gpus,
    load_models,
    params_from_safetensors_index,
    spec_from_hf_config,
)

MODELS = load_models()
GPUS = load_gpus()
WF, KV = load_formats()


def test_catalogs_have_sources() -> None:
    assert all(g.source for g in GPUS.values())
    assert all(w.source for w in WF.values())
    assert all(m.sources for m in MODELS.values())


def test_qwen38_kv_per_token_hand_computed() -> None:
    # 16 full-attention layers x (K and V) x 4 KV heads x 256 dims x 2 bytes = 65,536 bytes/token
    assert kv_bytes_per_token(MODELS["qwen3.8-27b"], KV["f16"]) == 16 * 2 * 4 * 256 * 2 == 65536
    assert kv_bytes_per_token(MODELS["qwen3.8-27b"], KV["q8_0"]) == pytest.approx(65536 / 2 * 1.0625)


def test_qwen38_linear_state_hand_computed() -> None:
    # per layer: SSM 48 x 128 x 128 x 4 B + conv 3 x (2*16*128 + 48*128) x 2 B; 48 linear layers
    per_layer = 48 * 128 * 128 * 4 + 3 * (2 * 16 * 128 + 48 * 128) * 2
    assert linear_state_bytes_per_sequence(MODELS["qwen3.8-27b"]) == 48 * per_layer == 153_944_064


def test_incomplete_spec_is_refused() -> None:
    with pytest.raises(IncompleteSpecError, match="full_attn_layers"):  # attention layout not modelled yet
        kv_bytes_per_token(MODELS["deepseek-v4-flash"], KV["f16"])


def test_measured_artifact_wins_over_estimate() -> None:
    spec = MODELS["deepseek-v4-flash"]
    b, src = weight_bytes(spec, WF["fp8"], artifact_format="native_fp4_fp8")
    assert b == 146e9
    assert "measured" in src
    est, src = weight_bytes(MODELS["qwen3.8-27b"], WF["q4_k_m"])
    assert est == pytest.approx(MODELS["qwen3.8-27b"].params_total * 4.8944 / 8)
    assert MODELS["qwen3.8-27b"].params_total == 27781427952  # exact, from the safetensors index
    assert "estimate" in src


def test_memory_estimate_and_capacity_are_consistent() -> None:
    spec = MODELS["qwen3.8-27b"]
    cap = max_cached_tokens(spec, WF["q4_k_m"], KV["f16"], n_sequences=1, n_gpus=2, gpu_memory_gb=16)
    assert cap > 0
    fits = estimate_memory(
        spec, WF["q4_k_m"], KV["f16"], cached_tokens=cap, n_sequences=1, n_gpus=2, gpu_memory_gb=16
    )
    too_big = estimate_memory(
        spec, WF["q4_k_m"], KV["f16"], cached_tokens=cap + 50_000, n_sequences=1, n_gpus=2, gpu_memory_gb=16
    )
    assert fits.fits
    assert not too_big.fits


def test_deepseek_v4_pro_needs_many_gpus_for_weights() -> None:
    spec = MODELS["deepseek-v4-pro"]
    assert min_gpus_for_weights(spec, WF["fp8"], GPUS["t4"], artifact_format="native_fp4_fp8") > 50
    assert min_gpus_for_weights(spec, WF["fp8"], GPUS["h200"], artifact_format="native_fp4_fp8") == 7


def test_moe_touched_fraction() -> None:
    spec = ModelSpec(
        key="moe",
        display_name="moe",
        params_total=30e9,
        params_active=3e9,
        n_layers=48,
        hidden_size=2048,
        num_experts=128,
        experts_per_token=8,
        moe_intermediate_size=768,
    )
    total = 15e9
    expert_share = spec.expert_params / spec.params_total  # type: ignore[operator]
    one = touched_weight_bytes(spec, total, 1)
    assert one == pytest.approx(total * (1 - expert_share) + total * expert_share * 8 / 128)
    many = touched_weight_bytes(spec, total, 10_000)
    assert many == pytest.approx(total, rel=1e-6)
    assert one < touched_weight_bytes(spec, total, 8) < many


def test_decode_speed_decreases_with_batch_and_context() -> None:
    spec, gpu = MODELS["qwen3.8-27b"], GPUS["t4"]
    calib = Calibration()
    speeds = [
        estimate_decode(
            spec,
            WF["q4_k_m"],
            KV["f16"],
            gpu,
            n_gpus=2,
            parallelism=Parallelism.TENSOR,
            batch=b,
            avg_context=4096,
            calib=calib,
        ).per_sequence_tps
        for b in (1, 4, 16)
    ]
    assert speeds[0] > speeds[1] > speeds[2]
    short = estimate_decode(
        spec,
        WF["q4_k_m"],
        KV["f16"],
        gpu,
        n_gpus=1,
        parallelism=Parallelism.LAYER,
        batch=1,
        avg_context=512,
        calib=calib,
    )
    long = estimate_decode(
        spec,
        WF["q4_k_m"],
        KV["f16"],
        gpu,
        n_gpus=1,
        parallelism=Parallelism.LAYER,
        batch=1,
        avg_context=65536,
        calib=calib,
    )
    assert short.per_sequence_tps > long.per_sequence_tps


def test_layer_split_does_not_add_bandwidth_but_tensor_parallel_does() -> None:
    spec, gpu, calib = MODELS["qwen3.8-27b"], GPUS["t4"], Calibration()
    kw = {"batch": 1, "avg_context": 1024, "calib": calib}
    one = estimate_decode(spec, WF["q4_k_m"], KV["f16"], gpu, n_gpus=1, parallelism=Parallelism.LAYER, **kw)
    layer = estimate_decode(spec, WF["q4_k_m"], KV["f16"], gpu, n_gpus=2, parallelism=Parallelism.LAYER, **kw)
    tensor = estimate_decode(
        spec, WF["q4_k_m"], KV["f16"], gpu, n_gpus=2, parallelism=Parallelism.TENSOR, **kw
    )
    assert layer.per_sequence_tps == pytest.approx(one.per_sequence_tps)
    assert tensor.per_sequence_tps == pytest.approx(one.per_sequence_tps * 2 * calib.tp_efficiency)


def test_hf_config_import_hybrid_standard_and_mla() -> None:
    hybrid = spec_from_hf_config(
        "h",
        {
            "text_config": {
                "num_hidden_layers": 64,
                "hidden_size": 5120,
                "num_attention_heads": 24,
                "num_key_value_heads": 4,
                "head_dim": 256,
                "layer_types": (["linear_attention"] * 3 + ["full_attention"]) * 16,
                "linear_num_key_heads": 16,
                "linear_num_value_heads": 48,
                "linear_key_head_dim": 128,
                "linear_value_head_dim": 128,
                "linear_conv_kernel_dim": 4,
                "mamba_ssm_dtype": "float32",
                "max_position_embeddings": 262144,
            }
        },
    )
    assert (hybrid.full_attn_layers, hybrid.linear_attn_layers) == (16, 48)
    assert kv_bytes_per_token(hybrid, KV["f16"]) == kv_bytes_per_token(MODELS["qwen3.8-27b"], KV["f16"])
    assert linear_state_bytes_per_sequence(hybrid) == linear_state_bytes_per_sequence(MODELS["qwen3.8-27b"])

    std = spec_from_hf_config(
        "s",
        {
            "num_hidden_layers": 40,
            "hidden_size": 5120,
            "num_attention_heads": 32,
            "num_key_value_heads": 8,
            "head_dim": 128,
        },
        params_total=24e9,
    )
    assert kv_bytes_per_token(std, KV["f16"]) == 40 * 2 * 8 * 128 * 2
    assert std.params_active == 24e9

    mla = spec_from_hf_config(
        "m",
        {
            "num_hidden_layers": 61,
            "hidden_size": 7168,
            "num_attention_heads": 128,
            "kv_lora_rank": 512,
            "qk_rope_head_dim": 64,
            "n_routed_experts": 256,
            "num_experts_per_tok": 8,
            "first_k_dense_replace": 3,
        },
    )
    assert kv_bytes_per_token(mla, KV["f16"]) == 61 * 576 * 2
    assert mla.moe_layers == 58
    assert mla.params_active is None


def test_params_from_safetensors_index() -> None:
    assert params_from_safetensors_index({"metadata": {"total_size": 54e9}}, 2.0) == 27e9
    assert params_from_safetensors_index({}) is None
    # FP8 checkpoint (Devstral Small 2): bytes / 2 would halve the count; total_parameters is exact
    fp8 = {"metadata": {"total_size": 25792912480, "total_parameters": 24011361840}}
    assert params_from_safetensors_index(fp8) == 24011361840


def test_planner_scales_with_team_and_rejects_impossible() -> None:
    spec, sc = MODELS["qwen3.8-27b"], load_scenarios()["chat"]
    calib = Calibration()
    small = plan_deployment(
        spec,
        WF["q4_k_m"],
        KV["f16"],
        GPUS["l40s"],
        sc,
        engineers=20,
        gpus_per_replica=1,
        parallelism=Parallelism.TENSOR,
        calib=calib,
    )
    big = plan_deployment(
        spec,
        WF["q4_k_m"],
        KV["f16"],
        GPUS["l40s"],
        sc,
        engineers=400,
        gpus_per_replica=1,
        parallelism=Parallelism.TENSOR,
        calib=calib,
    )
    assert small.feasible
    assert big.feasible
    assert big.total_gpus > small.total_gpus
    no_fit = plan_deployment(
        spec,
        WF["f16"],
        KV["f16"],
        GPUS["t4"],
        sc,
        engineers=20,
        gpus_per_replica=1,
        parallelism=Parallelism.TENSOR,
        calib=calib,
    )
    assert not no_fit.feasible
    assert no_fit.reason == "weights do not fit"
    no_fp8 = plan_deployment(
        spec,
        WF["fp8"],
        KV["f16"],
        GPUS["t4"],
        sc,
        engineers=20,
        gpus_per_replica=2,
        parallelism=Parallelism.TENSOR,
        calib=calib,
    )
    assert not no_fp8.feasible
    assert "FP8" in no_fp8.reason


def test_calibration_recovers_known_efficiency() -> None:
    """Synthetic measurements generated with a known efficiency must be recovered exactly."""
    true = Calibration(decode_bw_efficiency=0.42, prefill_compute_efficiency=0.2)
    spec_a = MODELS["qwen3.8-27b"]
    spec_b = spec_a.model_copy(update={"key": "qwen-b", "params_total": 14e9, "params_active": 14e9})
    specs = {"qwen3.8-27b": spec_a, "qwen-b": spec_b}
    ms = []
    for key, spec in specs.items():
        d = estimate_decode(
            spec,
            WF["q4_k_m"],
            KV["f16"],
            GPUS["t4"],
            n_gpus=2,
            parallelism=Parallelism.LAYER,
            batch=1,
            avg_context=300,
            calib=true,
        )
        ms.append(
            Measurement(
                engine="llama.cpp",
                model_key=key,
                weight_format="q4_k_m",
                gpu_key="t4",
                n_gpus=2,
                parallelism=Parallelism.LAYER,
                decode_tps_single=d.per_sequence_tps,
                decode_context=300,
                prefill_tps=None,
                prefill_prompt_tokens=None,
            )
        )
    got = fit(ms, specs, WF, KV["f16"], GPUS)
    assert got.decode_bw_efficiency == pytest.approx(0.42)
    rows = leave_one_model_out(ms, specs, WF, KV["f16"], GPUS)
    assert all(abs(r["decode_error_pct"]) < 0.1 for r in rows)


def test_team_report_sizes_complete_specs_and_lists_unverified_ones() -> None:
    from onprem_genai.sizing.cli import team_report  # noqa: PLC0415

    text = team_report(["qwen3.8-27b", "deepseek-v4-flash"], ["chat"], [25, 100], ["t4", "h100-nvl"])
    lines = text.splitlines()
    assert lines[0] == "| model | scenario | engineers | t4 | h100-nvl |"
    rows = [ln for ln in lines if ln.startswith("| Qwen3.8-27B | chat |")]
    assert len(rows) == 2
    assert "Not sized (unverified architecture fields): deepseek-v4-flash" in text


def test_calibration_from_probe_fits_dense_and_moe_separately() -> None:
    probe = json.loads(Path("docs/results/probe/run2-2026-10-28.json").read_text())
    ms = measurements_from_probe(probe)
    assert sorted(m.model_key for m in ms) == [
        "devstral-small-2-24b",
        "qwen3-coder-30b-a3b",
        "qwen3.6-35b-a3b",
        "qwen3.8-27b",
    ]
    assert all(m.parallelism is Parallelism.LAYER and m.n_gpus == 2 and m.weights_bytes for m in ms)
    specs = load_models()
    calib = fit(ms, specs, WF, KV["f16"], GPUS)
    assert calib.decode_bw_efficiency > calib.moe_decode_bw_efficiency  # MoE kernels reach less of the peak
    assert calib.prefill_compute_efficiency > calib.moe_prefill_compute_efficiency
    rows = {r["model"]: r for r in leave_one_model_out(ms, specs, WF, KV["f16"], GPUS)}
    assert all(abs(r["decode_error_pct"]) < 12 for r in rows.values())
    vllm = measurements_from_probe(probe, engine="vllm")
    assert [(m.model_key, m.weight_format) for m in vllm] == [("qwen3-coder-30b-a3b", "awq_int4_g128")]


def test_max_request_rate_matches_the_replica_count() -> None:
    spec, sc = load_models()["qwen3-coder-30b-a3b"], load_scenarios()["chat"]
    kw = {"gpus_per_replica": 2, "parallelism": Parallelism.LAYER, "calib": Calibration()}
    rate, plan = max_request_rate(spec, WF["q4_k_m"], KV["f16"], GPUS["t4"], sc, **kw)
    assert plan is not None
    assert rate > 0
    one = sc.model_copy(update={"headroom": 1.0, "peak_active_fraction": 1.0})
    n = round(rate * 3600 / 12)
    assert plan_deployment(spec, WF["q4_k_m"], KV["f16"], GPUS["t4"], one, engineers=n, **kw).replicas == 1
    assert (
        plan_deployment(spec, WF["q4_k_m"], KV["f16"], GPUS["t4"], one, engineers=n + 1, **kw).replicas == 2
    )
