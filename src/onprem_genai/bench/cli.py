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
) -> None:
    """Concurrency sweep for one traffic profile."""
    corpus = load_corpus(corpus_dir) if corpus_dir else synthetic_corpus()
    prof = make_profiles(corpus, scale)[profile]
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if disable_thinking else None
    levels = [int(x) for x in concurrency.split(",")]
    summaries = asyncio.run(sweep(base_url, model, prof, levels, requests_per_level, extra))
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
