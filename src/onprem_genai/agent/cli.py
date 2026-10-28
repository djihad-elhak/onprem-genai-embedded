"""`oge agent ...`: close traceability gaps in F´ by generating requirement-tagged unit tests."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from onprem_genai.agent.fprime import FprimeWorkspace
from onprem_genai.agent.graph import AgentConfig, AgentDeps
from onprem_genai.agent.knowledge import KnowledgeClient
from onprem_genai.agent.runner import (
    DEFAULT_MODULES,
    ScriptedModel,
    review_sheet,
    run_batch,
    select_targets,
    summarize,
)
from onprem_genai.llm import ChatModel

app = typer.Typer(
    help="Requirement-based unit-test generation agent (LangGraph) for F´.", no_args_is_help=True
)
console = Console()

FprimeOpt = Annotated[Path, typer.Option(help="F´ checkout with a generated unit-test build cache")]
GraphOpt = Annotated[Path | None, typer.Option(help="Graph snapshot served in-process over MCP")]
McpOpt = Annotated[str | None, typer.Option(envvar="OGE_MCP_URL", help="Knowledge MCP server URL (…/mcp)")]
ModuleOpt = Annotated[list[str] | None, typer.Option("--module", "-m", help="Component, e.g. Svc/ComStub")]
ReqOpt = Annotated[list[str] | None, typer.Option("--req", "-r", help="Requirement ID (repeatable)")]


def _mcp_target(mcp_url: str | None, graph: Path | None) -> Any:
    if mcp_url:
        return mcp_url
    if graph is None:
        raise typer.BadParameter("give --mcp-url (shared knowledge service) or --graph (in-process server)")
    from onprem_genai.knowledge.model import Graph  # noqa: PLC0415
    from onprem_genai.knowledge.store import InMemoryStore  # noqa: PLC0415
    from onprem_genai.mcp_server.server import build_server  # noqa: PLC0415

    return build_server(InMemoryStore(Graph.load(graph)))


@app.command("targets")
def targets(
    graph: GraphOpt = Path("artifacts/fprime_graph.jsonl.gz"),
    mcp_url: McpOpt = None,
    module: ModuleOpt = None,
) -> None:
    """List the traceability gaps the agent would work on."""

    async def go() -> None:
        async with KnowledgeClient(_mcp_target(mcp_url, graph)) as kb:
            for m in module or DEFAULT_MODULES:
                for g in sorted(await kb.gaps(m), key=lambda x: x["req_id"]):
                    console.print(f"{g['req_id']:<20} {m:<20} {g['text'][:90]}")

    asyncio.run(go())


@app.command("run")
def run(
    fprime: FprimeOpt = Path("third_party/fprime"),
    graph: GraphOpt = Path("artifacts/fprime_graph.jsonl.gz"),
    mcp_url: McpOpt = None,
    module: ModuleOpt = None,
    req: ReqOpt = None,
    base_url: Annotated[str | None, typer.Option(help="OpenAI-compatible LLM server root")] = None,
    model: str = "default",
    label: Annotated[str | None, typer.Option(help="Model name for reports and commit trailers")] = None,
    api_key: Annotated[str | None, typer.Option(envvar="OGE_API_KEY")] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    extra_body: Annotated[str | None, typer.Option(help="JSON merged into each LLM request")] = None,
    scripted: Annotated[Path | None, typer.Option(help="JSON of scripted answers (offline demo)")] = None,
    max_attempts: Annotated[int, typer.Option(min=1, max=10)] = 3,
    mutants: Annotated[int, typer.Option(min=0, help="Fault-detection mutants per verified requirement")] = 0,
    context_chars: int = 36000,
    commit: Annotated[bool, typer.Option(help="Commit verified tests on the run branch")] = True,
    branch: Annotated[str | None, typer.Option(help="Run branch (default oge-agent/<label>-<date>)")] = None,
    out: Annotated[
        Path | None, typer.Option(help="Results JSONL (default artifacts/agent/<label>.jsonl)")
    ] = None,
    fprime_util: Annotated[str | None, typer.Option(envvar="OGE_FPRIME_UTIL")] = None,
    jobs: Annotated[int | None, typer.Option(help="Parallel build jobs")] = None,
) -> None:
    """Generate, build, run and commit one unit test per requirement gap."""
    if scripted:
        answers = {
            k: v for k, v in json.loads(scripted.read_text(encoding="utf-8")).items() if not k.startswith("_")
        }
        llm: Any = ScriptedModel(answers)
        label = label or "scripted"
    elif base_url:
        client = ChatModel(
            base_url,
            model,
            api_key,
            temperature,
            0.95,
            max_tokens,
            json.loads(extra_body) if extra_body else None,
        )
        llm = client.complete
        label = label or model
    else:
        raise typer.BadParameter("--base-url is required (or --scripted)")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-").lower()
    branch = branch or f"oge-agent/{slug}-{datetime.now(UTC):%Y%m%d}"
    out = out or Path("artifacts/agent") / f"{slug}.jsonl"
    ws = FprimeWorkspace(fprime, fprime_util, jobs)
    cfg = AgentConfig(
        max_attempts=max_attempts,
        context_chars=context_chars,
        mutants=mutants,
        model_label=label,
        commit=commit,
    )

    def progress(rec: dict[str, Any], done: int, total: int) -> None:
        colour = {"passed": "green", "not_testable": "cyan", "suspected_defect": "magenta"}.get(
            rec["status"], "red"
        )
        stages = " → ".join(h["stage"] for h in rec["history"])
        console.print(
            f"[{done:>2}/{total}] {rec['req_id']:<20} [{colour}]{rec['status']:<16}[/] "
            f"{rec['wall_seconds']:6.1f}s  {stages}"
        )

    async def go() -> list[dict[str, Any]]:
        async with KnowledgeClient(_mcp_target(mcp_url, graph)) as kb:
            ids = await select_targets(kb, module, req)
            console.print(f"{len(ids)} requirement(s) → branch {branch}, results {out}")
            return await run_batch(AgentDeps(ws, kb, llm, cfg), ids, out, branch, progress)

    records = asyncio.run(go())
    _write_reports(records, out, label)


def _write_reports(records: list[dict[str, Any]], out: Path, label: str) -> None:
    summary = summarize(records)
    out.with_suffix(".summary.json").write_text(
        json.dumps({"label": label, **summary}, indent=1), encoding="utf-8"
    )
    out.with_suffix(".review.md").write_text(review_sheet(records, label), encoding="utf-8")
    console.print_json(json.dumps(summary))
    console.print(
        f"summary: {out.with_suffix('.summary.json')}  review sheet: {out.with_suffix('.review.md')}"
    )


@app.command("report")
def report(
    results: Annotated[Path, typer.Argument(help="Results JSONL of a run")],
    label: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Recompute the summary and review sheet of a run."""
    records = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()]
    _write_reports(records, results, label or results.stem)
