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
from rich.syntax import Syntax

from onprem_genai.agent.ci import DEFAULT_JOB, JenkinsCi
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
    verify_with_ci,
)
from onprem_genai.agent.trace import describe
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
CiUrlOpt = Annotated[
    str | None, typer.Option(envvar="OGE_JENKINS_MCP_URL", help="Jenkins MCP endpoint (…/mcp-server/mcp)")
]
CiUserOpt = Annotated[str | None, typer.Option(envvar="OGE_JENKINS_USER")]
CiSecretOpt = Annotated[str | None, typer.Option(envvar="OGE_JENKINS_TOKEN", help="API token or password")]
CiJobOpt = Annotated[str, typer.Option(help="Jenkins pipeline running the F´ unit tests")]


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
    max_tokens: int = 3072,
    extra_body: Annotated[str | None, typer.Option(help="JSON merged into each LLM request")] = None,
    scripted: Annotated[Path | None, typer.Option(help="JSON of scripted answers (offline demo)")] = None,
    max_attempts: Annotated[int, typer.Option(min=1, max=10)] = 3,
    mutants: Annotated[int, typer.Option(min=0, help="Fault-detection mutants per verified requirement")] = 0,
    context_chars: int = 32000,
    commit: Annotated[bool, typer.Option(help="Commit verified tests on the run branch")] = True,
    branch: Annotated[str | None, typer.Option(help="Run branch (default oge-agent/<label>-<date>)")] = None,
    out: Annotated[
        Path | None, typer.Option(help="Results JSONL (default artifacts/agent/<label>.jsonl)")
    ] = None,
    fprime_util: Annotated[str | None, typer.Option(envvar="OGE_FPRIME_UTIL")] = None,
    jobs: Annotated[int | None, typer.Option(help="Parallel build jobs")] = None,
    ci_url: CiUrlOpt = None,
    ci_user: CiUserOpt = None,
    ci_token: CiSecretOpt = None,
    ci_job: CiJobOpt = DEFAULT_JOB,
    trace: Annotated[bool, typer.Option(help="Print every agent step and the verified test code")] = False,
) -> None:
    """Generate, build, run and commit one unit test per requirement gap, then verify the branch in CI."""
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

    def show_step(req_id: str, node: str, update: dict[str, Any], state: dict[str, Any]) -> None:
        if node == "prepare":
            text = " ".join(str((state.get("requirement") or {}).get("text", "")).split())
            console.print(f"[bold cyan]▶ {req_id}[/] {text}", highlight=False)
        line = describe(node, update, state)
        if line is None:
            return
        bad = any(w in line for w in ("failed", "rejected", "error"))
        mark = "[red]✗[/]" if bad else "[green]✓[/]"
        console.print(f"  [bold]{node:<9}[/] {mark} {line}", highlight=False)
        if node == "commit" and state.get("patch") is not None:
            patch = state["patch"]
            code = "\n\n".join(d.text for d in patch.definitions)
            console.print(Syntax(code, "cpp", theme="ansi_dark", line_numbers=False, word_wrap=True))

    async def go() -> list[dict[str, Any]]:
        async with KnowledgeClient(_mcp_target(mcp_url, graph)) as kb:
            ids = await select_targets(kb, module, req)
            console.print(f"{len(ids)} requirement(s) → branch {branch}, results {out}")
            records = await run_batch(
                AgentDeps(ws, kb, llm, cfg), ids, out, branch, progress, trace=show_step if trace else None
            )
        if ci_url:
            console.print(f"CI: Jenkins job {ci_job} on {branch} …")
            ci = await verify_with_ci(JenkinsCi(ci_url, ci_user, ci_token, ci_job), records, branch, out)
            console.print(f"CI: {ci['result'] if ci else 'nothing to verify'}")
        return records

    records = asyncio.run(go())
    _write_reports(records, out, label, quiet=trace)


def _write_reports(records: list[dict[str, Any]], out: Path, label: str, quiet: bool = False) -> None:
    summary = summarize(records)
    ci_file = out.with_suffix(".ci.json")
    ci = json.loads(ci_file.read_text(encoding="utf-8")) if ci_file.exists() else None
    if ci:
        summary["ci"] = {k: ci.get(k) for k in ("job", "build_number", "result", "tests", "url", "seconds")}
    text = json.dumps({"label": label, **summary}, indent=1)
    out.with_suffix(".summary.json").write_text(text, encoding="utf-8")
    out.with_suffix(".review.md").write_text(review_sheet(records, label, ci), encoding="utf-8")
    if quiet:
        mut = summary["mutation"]
        console.print(
            f"verified {summary['status'].get('passed', 0)}/{summary['targets']} · "
            f"mutants killed {mut['killed']}/{mut['valid_mutants']}"
        )
    else:
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


@app.command("ci")
def ci_cmd(
    branch: Annotated[str, typer.Option(help="Branch of the F´ repository to test")],
    module: Annotated[list[str], typer.Option("--module", "-m", help="Component, e.g. Svc/ComStub")],
    ci_url: CiUrlOpt = None,
    ci_user: CiUserOpt = None,
    ci_token: CiSecretOpt = None,
    ci_job: CiJobOpt = DEFAULT_JOB,
) -> None:
    """Run the Jenkins unit-test pipeline on a branch through the Jenkins MCP server and wait for it."""
    if not ci_url:
        raise typer.BadParameter("--ci-url (or OGE_JENKINS_MCP_URL) is required")
    res = asyncio.run(JenkinsCi(ci_url, ci_user, ci_token, ci_job).run(branch, module))
    console.print_json(json.dumps(res.as_dict()))
    if not res.passed:
        raise typer.Exit(1)
