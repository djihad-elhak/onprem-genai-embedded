"""`oge bench ...` commands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from onprem_genai.bench.loadgen import sweep
from onprem_genai.bench.profiles import load_corpus, make_profiles, synthetic_corpus

app = typer.Typer(help="Benchmark an OpenAI-compatible inference server.", no_args_is_help=True)
console = Console()


@app.command("run")
def run(
    base_url: Annotated[str, typer.Option(help="Server root, e.g. http://127.0.0.1:8080")],
    model: str = "default",
    profile: Annotated[str, typer.Option(help="completion | chat | agent")] = "chat",
    concurrency: Annotated[str, typer.Option(help="Comma-separated levels")] = "1,2,4,8",
    requests_per_level: int = 16,
    corpus_dir: Annotated[Path | None, typer.Option(help="Source tree for realistic prompts")] = None,
    scale: Annotated[float, typer.Option(help="Prompt-size multiplier")] = 1.0,
    disable_thinking: bool = False,
    out: Path | None = None,
    api_key: Annotated[str | None, typer.Option(envvar="OGE_API_KEY")] = None,
) -> None:
    """Concurrency sweep for one traffic profile."""
    corpus = load_corpus(corpus_dir) if corpus_dir else synthetic_corpus()
    prof = make_profiles(corpus, scale)[profile]
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if disable_thinking else None
    levels = [int(x) for x in concurrency.split(",")]
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    summaries = asyncio.run(sweep(base_url, model, prof, levels, requests_per_level, extra, headers=headers))
    t = Table(
        "conc.",
        "req",
        "err",
        "out tok/s",
        "TTFT p50",
        "TTFT p95",
        "TPOT p50 ms",
        "TPOT p95 ms",
        title=f"{profile} @ {base_url}",
    )
    for s in summaries:
        t.add_row(
            str(s.concurrency),
            str(s.n_requests),
            str(s.n_errors),
            f"{s.output_tps:.1f}",
            f"{s.ttft_p50_s or 0:.2f}",
            f"{s.ttft_p95_s or 0:.2f}",
            f"{s.tpot_p50_ms or 0:.1f}",
            f"{s.tpot_p95_ms or 0:.1f}",
        )
    console.print(t)
    if out:
        out.write_text(json.dumps([s.as_dict() for s in summaries], indent=2), encoding="utf-8")


@app.command("pull-gguf")
def pull_gguf(
    repo: Annotated[str, typer.Argument(help="Hugging Face repo, e.g. unsloth/Qwen3.5-4B-GGUF")],
    quant: Annotated[str, typer.Argument(help="Quantization, e.g. Q4_K_M or Q8_0")],
    out: Annotated[Path, typer.Option(help="Destination file (single-file models) or directory (sharded)")],
) -> None:
    """Download one GGUF quantization (resolved from the repo listing) to a stable local path."""
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from onprem_genai.bench.engines import download_gguf  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        first = download_gguf(repo, quant, Path(tmp))
        shards = sorted(first.parent.glob("*.gguf"))
        if len(shards) == 1:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(first, out)
            console.print(f"{repo}:{quant} -> {out} ({out.stat().st_size / 1e9:.2f} GB)")
        else:
            out.mkdir(parents=True, exist_ok=True)
            for s in shards:
                shutil.copy2(s, out / s.name)
            console.print(
                f"{repo}:{quant} -> {out}/ ({len(shards)} shards; pass the first one to the server)"
            )
