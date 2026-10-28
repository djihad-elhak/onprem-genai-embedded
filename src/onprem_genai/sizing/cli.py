"""`oge sizing ...` commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.table import Table

from onprem_genai.sizing.memory import estimate_memory, max_cached_tokens
from onprem_genai.sizing.performance import Calibration, Parallelism, estimate_decode, estimate_prefill_tps
from onprem_genai.sizing.planner import best_plan_per_gpu, load_scenarios
from onprem_genai.sizing.specs import (
    IncompleteSpecError,
    load_formats,
    load_gpus,
    load_json,
    load_models,
    params_from_safetensors_index,
    spec_from_hf_config,
)

app = typer.Typer(
    help="Memory, throughput and GPU capacity planning for on-prem LLM serving.", no_args_is_help=True
)
console = Console()


def _calibration(path: Path | None) -> Calibration:
    if path is None:
        return Calibration()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Calibration(**data)


@app.command("models")
def list_models() -> None:
    """List model specs and which fields are still unverified."""
    t = Table("key", "params (B)", "active (B)", "layers", "full-attn", "kv heads", "head dim", "status")
    for m in load_models().values():
        missing = [
            f for f in ("params_total", "full_attn_layers", "kv_heads", "head_dim") if getattr(m, f) is None
        ]
        if m.mla_kv_dim is not None:
            missing = [f for f in missing if f not in ("kv_heads", "head_dim")]
        t.add_row(
            m.key,
            f"{(m.params_total or 0) / 1e9:.1f}",
            f"{(m.params_active or 0) / 1e9:.1f}",
            str(m.n_layers),
            str(m.full_attn_layers),
            str(m.kv_heads),
            str(m.head_dim),
            "complete" if not missing else "pending: " + ",".join(missing),
        )
    console.print(t)


@app.command("gpus")
def list_gpus() -> None:
    """List the GPU catalog (datasheet values with sources)."""
    t = Table("key", "name", "memory GB", "bandwidth GB/s", "FP16 dense TFLOPS", "FP8", "BF16")
    for g in load_gpus().values():
        t.add_row(
            g.key,
            g.name,
            f"{g.memory_gb:g}",
            f"{g.bandwidth_gbs:g}",
            f"{g.fp16_dense_tflops:g}",
            "yes" if g.supports_fp8 else "no",
            "yes" if g.supports_bf16 else "no",
        )
    console.print(t)


@app.command("memory")
def memory(
    model: str,
    weights: Annotated[str, typer.Option(help="Weight format, e.g. q4_k_m, awq_int4_g128, f16")] = "q4_k_m",
    kv: Annotated[str, typer.Option(help="KV-cache format: f16, q8_0, fp8")] = "f16",
    gpu: str = "t4",
    gpus: int = 1,
    context: Annotated[int, typer.Option(help="Total cached tokens across all sequences")] = 16384,
    sequences: int = 1,
    overhead_gb: float = 1.0,
) -> None:
    """Memory breakdown for one deployment."""
    spec, g = load_models()[model], load_gpus()[gpu]
    wf, kf = load_formats()
    est = estimate_memory(
        spec,
        wf[weights],
        kf[kv],
        cached_tokens=context,
        n_sequences=sequences,
        n_gpus=gpus,
        gpu_memory_gb=g.memory_gb,
        overhead_gb_per_gpu=overhead_gb,
    )
    cap = max_cached_tokens(
        spec,
        wf[weights],
        kf[kv],
        n_sequences=sequences,
        n_gpus=gpus,
        gpu_memory_gb=g.memory_gb,
        overhead_gb_per_gpu=overhead_gb,
    )
    t = Table(title=f"{spec.display_name} on {gpus}x {g.name}", show_header=False)
    for k, v in est.as_dict().items():
        t.add_row(k, f"{v:.3f}" if isinstance(v, float) else str(v))
    t.add_row("max_cached_tokens_that_fit", f"{cap:,}")
    console.print(t)


@app.command("throughput")
def throughput(
    model: str,
    weights: str = "q4_k_m",
    kv: str = "f16",
    gpu: str = "t4",
    gpus: int = 1,
    parallelism: Parallelism = Parallelism.LAYER,
    context: int = 2048,
    calibration: Path | None = None,
) -> None:
    """Predicted decode speed vs batch size, and prefill speed."""
    spec, g = load_models()[model], load_gpus()[gpu]
    wf, kf = load_formats()
    calib = _calibration(calibration)
    t = Table("batch", "per-sequence tok/s", "aggregate tok/s", "bound", title=f"calibration: {calib.source}")
    for b in (1, 2, 4, 8, 16, 32, 64):
        e = estimate_decode(
            spec,
            wf[weights],
            kf[kv],
            g,
            n_gpus=gpus,
            parallelism=parallelism,
            batch=b,
            avg_context=context,
            calib=calib,
        )
        t.add_row(str(b), f"{e.per_sequence_tps:.1f}", f"{e.aggregate_tps:.1f}", e.bound)
    console.print(t)
    p = estimate_prefill_tps(
        spec, g, n_gpus=gpus, parallelism=parallelism, prompt_tokens=context, calib=calib
    )
    console.print(f"prefill ≈ {p:,.0f} tok/s for a {context}-token prompt")


@app.command("plan")
def plan(
    model: str,
    weights: str = "q4_k_m",
    kv: str = "f16",
    scenario: str = "chat_agents",
    engineers: int = 100,
    calibration: Path | None = None,
    artifact: Annotated[str | None, typer.Option(help="Use a measured artifact format from the spec")] = None,
    json_out: Path | None = None,
) -> None:
    """Number of GPUs per GPU type to serve a team, under explicit workload assumptions."""
    spec = load_models()[model]
    wf, kf = load_formats()
    sc = load_scenarios()[scenario]
    plans = best_plan_per_gpu(
        spec,
        wf[weights],
        kf[kv],
        load_gpus(),
        sc,
        engineers=engineers,
        calib=_calibration(calibration),
        artifact_format=artifact,
    )
    t = Table(
        "GPU",
        "feasible",
        "GPUs/replica",
        "replicas",
        "total GPUs",
        "batch",
        "tok/s/user",
        "TTFT s",
        title=f"{spec.display_name} · {weights} · {scenario} · {engineers} engineers",
    )
    for p in plans:
        t.add_row(
            p.gpu,
            "yes" if p.feasible else f"no ({p.reason})",
            str(p.gpus_per_replica),
            str(p.replicas),
            str(p.total_gpus),
            str(p.batch_per_replica),
            f"{p.per_sequence_tps:g}",
            ", ".join(f"{k}={v}" for k, v in p.ttft_s.items()),
        )
    console.print(t)
    if json_out:
        json_out.write_text(json.dumps([p.as_dict() for p in plans], indent=2), encoding="utf-8")


def team_report(
    models: list[str],
    scenarios: list[str],
    team_sizes: list[int],
    gpus: list[str] | None = None,
    weights: str = "q4_k_m",
    kv: str = "f16",
    calib: Calibration | None = None,
) -> str:
    """Markdown: total GPUs per GPU type for each (model, scenario, team size); unknown specs are listed."""
    all_specs, (wf, kf), all_sc = load_models(), load_formats(), load_scenarios()
    gpu_table = load_gpus()
    names = gpus or list(gpu_table)
    head = "| model | scenario | engineers | " + " | ".join(names) + " |"
    lines = [head, "|" + "---|" * (3 + len(names))]
    pending: list[str] = []
    for m in models:
        spec = all_specs[m]
        try:
            rows = [
                (
                    sc,
                    n,
                    best_plan_per_gpu(
                        spec,
                        wf[weights],
                        kf[kv],
                        gpu_table,
                        all_sc[sc],
                        engineers=n,
                        calib=calib or Calibration(),
                    ),
                )
                for sc in scenarios
                for n in team_sizes
            ]
        except IncompleteSpecError as exc:
            pending.append(str(exc).split(" Import ")[0])
            continue
        for sc, n, plans in rows:
            by_gpu = {p.gpu: p for p in plans}
            cells = [
                f"{p.total_gpus} ({p.gpus_per_replica}×{p.replicas})" if p and p.feasible else "–"
                for p in (by_gpu.get(g) for g in names)
            ]
            lines.append(f"| {spec.display_name} | {sc} | {n} | " + " | ".join(cells) + " |")
    notes = ["", "Cells: total GPUs (GPUs per replica × replicas); – = infeasible (memory or SLO)."]
    if pending:
        notes += ["", "Not sized (unverified architecture fields): " + "; ".join(sorted(set(pending)))]
    return "\n".join(lines + notes) + "\n"


@app.command("report")
def report(
    model: Annotated[list[str], typer.Option("--model", "-m")],
    scenario: Annotated[list[str] | None, typer.Option("--scenario", "-s")] = None,
    engineers: Annotated[list[int] | None, typer.Option("--engineers", "-n")] = None,
    gpu: Annotated[list[str] | None, typer.Option("--gpu", "-g")] = None,
    weights: str = "q4_k_m",
    kv: str = "f16",
    calibration: Path | None = None,
    out: Path | None = None,
) -> None:
    """Team sizing table (markdown) across models, scenarios and team sizes."""
    text = team_report(
        model,
        scenario or ["chat", "chat_agents", "full"],
        engineers or [25, 100, 400],
        gpu,
        weights,
        kv,
        _calibration(calibration),
    )
    if out:
        out.write_text(text, encoding="utf-8")
    typer.echo(text)


@app.command("import-config")
def import_config(
    key: str,
    config: Annotated[Path, typer.Option(help="Path to the model's config.json")],
    hf_repo: str,
    display_name: str | None = None,
    index: Annotated[
        Path | None, typer.Option(help="model.safetensors.index.json for the exact parameter count")
    ] = None,
    dtype_bytes: float = 2.0,
    params_active: float | None = None,
    models_file: Annotated[Path | None, typer.Option(help="models.yaml to update in place")] = None,
) -> None:
    """Create or update a model spec from its official config.json (keeps measured artifacts)."""
    params = params_from_safetensors_index(load_json(index), dtype_bytes) if index else None
    spec = spec_from_hf_config(
        key,
        load_json(config),
        hf_repo=hf_repo,
        display_name=display_name,
        params_total=params,
        params_active=params_active,
        source=f"config.json of {hf_repo}",
    )
    entry = spec.model_dump(exclude={"key"}, exclude_none=True)
    if models_file:
        raw = yaml.safe_load(models_file.read_text(encoding="utf-8"))
        old = raw["models"].get(key, {})
        entry["artifacts"] = old.get("artifacts", []) or entry.get("artifacts", [])
        entry["sources"] = {**old.get("sources", {}), **entry.get("sources", {})}
        if index:
            entry["sources"]["params_total"] = f"model.safetensors.index.json of {hf_repo}"
        for k in ("family", "license"):
            if k in old:
                entry.setdefault(k, old[k])
        if display_name is None and "display_name" in old:
            entry["display_name"] = old["display_name"]
        # config.json does not state the active parameters of a MoE model: keep the documented value
        if params_active is None and entry.get("params_active") is None and old.get("params_active"):
            entry["params_active"] = old["params_active"]
            previous = old.get("sources", {}).get("architecture", "")
            entry["sources"].setdefault("params_active", f"kept from the previous entry: {previous}")
        first = ("display_name", "family", "hf_repo", "license")
        head = {k: entry[k] for k in first if k in entry}
        entry = head | {k: v for k, v in entry.items() if k not in first}
        raw["models"][key] = entry
        text = models_file.read_text(encoding="utf-8")
        header = "".join(ln for ln in text.splitlines(keepends=True)[:20] if ln.startswith("#"))
        models_file.write_text(
            header + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8"
        )
        console.print(f"updated {key} in {models_file}")
    else:
        console.print(yaml.safe_dump({key: entry}, sort_keys=False, allow_unicode=True))
