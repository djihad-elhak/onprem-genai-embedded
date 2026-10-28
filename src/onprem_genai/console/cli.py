"""``oge console``: serve the engineering console."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Engineering console: a web application over the platform.", no_args_is_help=True)

RESULTS = Path("docs/results/bench/run3-2026-10-28/agent-v2")


@app.command("serve")
def serve(
    graph: Annotated[Path, typer.Option(help="Knowledge-graph snapshot")] = Path(
        "artifacts/fprime_graph.jsonl.gz"
    ),
    fprime: Annotated[
        Path | None,
        typer.Option(help="F´ checkout prepared with scripts/setup_fprime_ut.sh (enables agent runs)"),
    ] = None,
    db: Annotated[Path, typer.Option(help="SQLite file for runs, results and reviews")] = Path(
        "artifacts/console/console.db"
    ),
    host: Annotated[
        str, typer.Option(help="Address to listen on; keep 127.0.0.1 unless behind a proxy")
    ] = "127.0.0.1",
    port: int = 8770,
    fprime_util: Annotated[str | None, typer.Option(envvar="OGE_FPRIME_UTIL")] = None,
    import_results: Annotated[
        list[Path] | None,
        typer.Option("--import-results", help="Agent results JSONL to show for review (repeatable)"),
    ] = None,
    import_label: Annotated[
        str, typer.Option(help="Source name of the imported results")
    ] = "Benchmark run 3",
    prereview: Annotated[
        Path | None, typer.Option(help="AI pre-review table shown as suggestions next to imported tests")
    ] = None,
    replay: Annotated[
        list[Path] | None,
        typer.Option(
            "--replay", help="Agent results JSONL whose verified answers can be replayed (repeatable)"
        ),
    ] = None,
    benchmark_defaults: Annotated[
        bool,
        typer.Option(help="Import and replay the run-3 benchmark results of this repository when present"),
    ] = True,
    jobs: Annotated[int | None, typer.Option(help="Parallel build jobs for agent runs")] = None,
) -> None:
    """Serve the console (http://127.0.0.1:8770 by default)."""
    import uvicorn  # noqa: PLC0415

    from onprem_genai.console.app import ConsoleConfig, create_app  # noqa: PLC0415

    imports = list(import_results or [])
    replays = list(replay or [])
    review_hints = prereview
    if benchmark_defaults and RESULTS.exists():
        # Qwen3-Coder first: its recorded answers are preferred for replay (faster model, more verified ones)
        defaults = sorted(
            RESULTS.glob("*__llamacpp.jsonl"), key=lambda p: (not p.name.startswith("qwen"), p.name)
        )
        imports = imports or defaults
        replays = replays or defaults
        review_hints = review_hints or RESULTS / "ai-prereview.md"
    cfg = ConsoleConfig(
        graph=graph,
        db=db,
        fprime=fprime,
        fprime_util=fprime_util,
        artifacts=db.parent,
        imports=[(import_label, p) for p in imports],
        prereview=review_hints,
        replay=replays,
        jobs=jobs,
    )
    typer.echo(f"Loading the knowledge graph from {graph} …")
    application = create_app(cfg)
    typer.echo(f"Engineering console: http://{host}:{port}")
    uvicorn.run(application, host=host, port=port, log_level="warning", proxy_headers=False)
