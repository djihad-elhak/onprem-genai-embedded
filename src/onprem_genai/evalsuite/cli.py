"""`oge eval ...` commands: list, validate and run the embedded C evaluation suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from onprem_genai.evalsuite import runner
from onprem_genai.evalsuite.tasks import Task, load_tasks
from onprem_genai.evalsuite.validate import validate_task

app = typer.Typer(
    help="Embedded C evaluation suite (generation, test generation, refactoring, docs).", no_args_is_help=True
)
console = Console()

CategoryOpt = Annotated[
    list[str] | None, typer.Option("--category", "-c", help="generate|testgen|refactor|document")
]
TaskOpt = Annotated[list[str] | None, typer.Option("--task", "-t", help="Task id (repeatable)")]


def _select(categories: list[str] | None, task_ids: list[str] | None) -> list[Task]:
    tasks = load_tasks(categories=categories)
    if task_ids:
        unknown = set(task_ids) - {t.id for t in tasks}
        if unknown:
            raise typer.BadParameter(f"unknown task(s): {', '.join(sorted(unknown))}")
        tasks = [t for t in tasks if t.id in task_ids]
    return tasks


@app.command("list")
def list_tasks(category: CategoryOpt = None) -> None:
    """List the tasks of the suite."""
    table = Table("id", "category", "domain", "title")
    for t in load_tasks(categories=category):
        table.add_row(t.id, t.category.value, t.domain, t.title)
    console.print(table)
    console.print(f"suite fingerprint: {runner.suite_fingerprint()}")


@app.command("validate")
def validate(category: CategoryOpt = None, task: TaskOpt = None) -> None:
    """Check the suite itself: references pass, stubs fail, reference tests kill every mutant."""
    bad = 0
    for t in _select(category, task):
        v = validate_task(t)
        bad += not v.ok
        console.print(
            f"[{'green' if v.ok else 'red'}]{'OK ' if v.ok else 'BAD'}[/] {t.id} {'; '.join(v.problems)}"
        )
    if bad:
        raise typer.Exit(1)


@app.command("run")
def run(
    base_url: Annotated[str | None, typer.Option(help="OpenAI-compatible server root")] = None,
    model: Annotated[str, typer.Option(help="Model name sent to the server")] = "default",
    label: Annotated[str | None, typer.Option(help="Name shown in reports (defaults to --model)")] = None,
    out: Annotated[Path, typer.Option(help="Report JSON")] = Path("artifacts/eval/report.json"),
    category: CategoryOpt = None,
    task: TaskOpt = None,
    samples: Annotated[int, typer.Option(min=1, help="Samples per task (pass@k)")] = 1,
    temperature: float = 0.2,
    top_p: float = 0.95,
    max_tokens: int = 4096,
    concurrency: Annotated[int, typer.Option(min=1)] = 4,
    timeout: Annotated[float, typer.Option(help="Per-request timeout (s)")] = 900,
    extra_body: Annotated[
        str | None,
        typer.Option(
            help="JSON merged into each request, e.g. "
            '\'{"chat_template_kwargs": {"enable_thinking": false}}\''
        ),
    ] = None,
    api_key: Annotated[str | None, typer.Option(envvar="OGE_API_KEY")] = None,
    reference: Annotated[
        bool, typer.Option(help="Answer with the reference solutions (harness check)")
    ] = False,
    resume: Annotated[bool, typer.Option(help="Reuse finished jobs from <out>.partial.jsonl")] = True,
) -> None:
    """Evaluate a model served behind an OpenAI-compatible endpoint."""
    tasks = _select(category, task)
    if reference:
        generate: runner.Generator = runner.reference_generator
        model = label or "reference"
    elif base_url:
        generate = runner.ChatClient(
            base_url,
            model,
            api_key,
            temperature,
            top_p,
            max_tokens,
            json.loads(extra_body) if extra_body else None,
            timeout,
        )
    else:
        raise typer.BadParameter("--base-url is required (or --reference)")
    partial = out.with_suffix(".partial.jsonl")
    if not resume:
        partial.unlink(missing_ok=True)

    def progress(r: runner.JobResult, done: int, total: int) -> None:
        mark = "[green]pass[/]" if r.passed else ("[yellow]error[/]" if r.error else "[red]fail[/]")
        console.print(f"[{done:>3}/{total}] {r.task:<24} s{r.sample} {mark} {r.latency_s:7.1f}s")

    results = runner.run_suite(tasks, generate, samples, concurrency, partial, progress)
    meta: dict[str, Any] = {
        "model": model,
        "label": label or model,
        "base_url": base_url,
        "params": {
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "extra_body": json.loads(extra_body) if extra_body else None,
        },
    }
    report = runner.build_report(results, samples, meta)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    partial.unlink(missing_ok=True)
    console.print(runner.markdown_table([report]))
    console.print_json(json.dumps(report["summary"]))
    console.print(f"report: {out}")


@app.command("report")
def report(
    reports: Annotated[list[Path], typer.Argument(help="Report JSON files to compare")],
    out: Annotated[Path | None, typer.Option(help="Write the markdown table here")] = None,
    failures: Annotated[bool, typer.Option(help="Also list failed tasks per report")] = False,
) -> None:
    """Compare run reports side by side (markdown)."""
    loaded = [json.loads(p.read_text(encoding="utf-8")) for p in reports]
    text = runner.markdown_table(loaded)
    if failures:
        for rep in loaded:
            failed = sorted({r["task"] for r in rep["results"] if not r["passed"]})
            text += f"\n**{rep['meta'].get('label')}** failed: {', '.join(failed) or 'none'}\n"
    if out:
        out.write_text(text, encoding="utf-8")
    typer.echo(text)
