"""`oge knowledge ...` and `oge mcp ...` commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from onprem_genai.knowledge import traceability as tr
from onprem_genai.knowledge.model import Graph
from onprem_genai.knowledge.retrieval import CachedEmbedder, Embedder, OpenAIEmbedder

app = typer.Typer(help="Build and query the engineering knowledge graph.", no_args_is_help=True)
mcp_app = typer.Typer(help="Serve the knowledge graph over the Model Context Protocol.", no_args_is_help=True)
console = Console()

DEFAULT_GRAPH = Path("artifacts/fprime_graph.jsonl.gz")
GraphOpt = Annotated[Path, typer.Option(help="Graph snapshot (.jsonl.gz)")]


def make_embedder(spec: str | None, cache_dir: Path | None = None) -> Embedder | None:
    """``openai:<base_url>|<model>`` or ``st:<hf-model>``; None disables dense retrieval."""
    if not spec:
        return None
    emb: Embedder
    if spec.startswith("openai:"):
        base, _, model = spec.removeprefix("openai:").partition("|")
        emb = OpenAIEmbedder(
            base,
            model or "default",
            query_instruction=tr.QUERY_INSTRUCTION,
            api_key=os.environ.get("OGE_API_KEY"),
        )
    elif spec.startswith("st:"):
        from onprem_genai.knowledge.retrieval import SentenceTransformerEmbedder  # noqa: PLC0415

        emb = SentenceTransformerEmbedder(spec.removeprefix("st:"), query_instruction=tr.QUERY_INSTRUCTION)
    else:
        raise typer.BadParameter(f"unknown embedder spec {spec!r}")
    return CachedEmbedder(emb, cache_dir) if cache_dir else emb


@app.command("ingest")
def ingest(
    fprime_root: Annotated[Path, typer.Argument(help="F´ checkout (scripts/fetch_fprime.sh)")] = Path(
        "third_party/fprime"
    ),
    out: GraphOpt = DEFAULT_GRAPH,
    audit_out: Annotated[Path | None, typer.Option(help="Write traceability audit findings (JSON)")] = None,
) -> None:
    """Parse code, tests, requirements and design docs into a graph snapshot."""
    from onprem_genai.knowledge.fprime.ingest import ingest_fprime  # noqa: PLC0415

    g, report = ingest_fprime(fprime_root)
    g.save(out)
    t = Table("metric", "value", title=f"F´ ingestion → {out}")
    for k, v in report.__dict__.items():
        t.add_row(k, str(len(v)) if isinstance(v, list) else f"{v:,}")
    console.print(t)
    if audit_out:
        audit_out.parent.mkdir(parents=True, exist_ok=True)
        findings = tr.audit_findings(report.tags_to_undefined_requirement, report.tags_cross_module)
        findings["details"] = {
            "undefined": report.tags_to_undefined_requirement,
            "cross_module": report.tags_cross_module,
        }
        audit_out.write_text(json.dumps(findings, indent=2), encoding="utf-8")


@app.command("trace-eval")
def trace_eval(
    graph: GraphOpt = DEFAULT_GRAPH,
    embedder: Annotated[str | None, typer.Option(help="openai:<url>|<model> or st:<hf-model>")] = None,
    embed_cache: Path | None = None,
    llm_base_url: Annotated[
        str | None, typer.Option(help="OpenAI-compatible chat server for reranking")
    ] = None,
    llm_model: str = "default",
    llm_top_n: int = 10,
    disable_thinking: bool = False,
    out: Annotated[Path | None, typer.Option(help="Results JSON")] = None,
    bootstrap: int = 1000,
) -> None:
    """Requirement→test traceability recovery benchmark (tags masked, ranked against all test cases)."""
    g = Graph.load(graph)
    ds = tr.build_dataset(g)
    bm25 = tr.bm25_ranker(ds)
    rankers: dict[str, tr.Ranker] = {
        "bm25": bm25,
        "graph": tr.graph_ranker(ds),
        "graph+bm25": tr.graph_constrained(ds, bm25),
    }
    emb = make_embedder(embedder, embed_cache)
    best = rankers["graph+bm25"]
    if emb is not None:
        dense = tr.dense_ranker(ds, emb)
        rankers["dense"] = dense
        rankers["graph+dense"] = tr.graph_constrained(ds, dense)
        rankers["graph+rrf(bm25,dense)"] = best = tr.graph_constrained(ds, tr.fused([bm25, dense]))
    if llm_base_url:
        extra = {"chat_template_kwargs": {"enable_thinking": False}} if disable_thinking else None
        judge = tr.LlmJudge(llm_base_url, llm_model, extra_body=extra, api_key=os.environ.get("OGE_API_KEY"))
        rankers[f"{_last(rankers)}+llm-rerank@{llm_top_n}"] = tr.llm_reranked(ds, best, judge, llm_top_n)

    results: dict[str, Any] = {
        "dataset": {
            "requirements": len(ds.req_ids),
            "candidates": len(ds.candidates),
            "commit": g.meta.get("commit"),
            "embedder": getattr(emb, "name", None),
            "llm": llm_model if llm_base_url else None,
        },
        "methods": {},
    }
    t = Table(
        "method",
        "MAP",
        "MRR",
        "R@1",
        "R@5",
        "R@10",
        "nDCG@10",
        title=f"Traceability recovery · {len(ds.req_ids)} requirements · {len(ds.candidates)} candidates",
    )
    for name, rk in rankers.items():
        res = tr.evaluate(ds, rk, bootstrap=bootstrap)
        results["methods"][name] = res
        m = res["metrics"]
        t.add_row(
            name,
            *(f"{m[k]['mean']:.3f}" for k in ("ap", "rr", "recall@1", "recall@5", "recall@10", "ndcg@10")),
        )
    console.print(t)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")


def _last(rankers: dict[str, tr.Ranker]) -> str:
    return list(rankers)[-1]


@app.command("gaps")
def gaps(graph: GraphOpt = DEFAULT_GRAPH, out: Path | None = None, top_k: int = 3) -> None:
    """Requirements with a test verification method but no tagged test, with suggested candidate tests."""
    g = Graph.load(graph)
    ds = tr.build_dataset(g)
    rows = tr.gap_report(g, ds, tr.graph_constrained(ds, tr.bm25_ranker(ds)), top_k=top_k)
    console.print(f"{len(rows)} requirements specify test verification but have no tagged test")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, indent=2), encoding="utf-8")


@app.command("load-neo4j")
def load_neo4j(
    graph: GraphOpt = DEFAULT_GRAPH,
    uri: str = typer.Option("bolt://localhost:7687", envvar="NEO4J_URI"),
    user: str = typer.Option("neo4j", envvar="NEO4J_USER"),
    password: str = typer.Option(..., envvar="NEO4J_PASSWORD", prompt=True, hide_input=True),
    wipe: bool = False,
) -> None:
    """Load a snapshot into Neo4j (idempotent MERGE)."""
    from onprem_genai.knowledge.neo4j_store import connect, load_graph  # noqa: PLC0415

    driver = connect(uri, user, password)
    try:
        counts = load_graph(driver, Graph.load(graph), wipe=wipe)
    finally:
        driver.close()
    console.print(counts)


@mcp_app.command("serve")
def serve(
    graph: GraphOpt = DEFAULT_GRAPH,
    transport: Annotated[str, typer.Option(help="stdio | streamable-http")] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    embedder: Annotated[
        str | None, typer.Option(envvar="OGE_MCP_EMBEDDER", help="Dense retrieval backend (optional)")
    ] = None,
    embed_cache: Annotated[Path | None, typer.Option(envvar="OGE_MCP_EMBED_CACHE")] = None,
    neo4j: Annotated[
        bool, typer.Option(envvar="OGE_MCP_NEO4J", help="Answer graph queries from Neo4j (NEO4J_* env vars)")
    ] = False,
    allowed_host: Annotated[
        list[str] | None,
        typer.Option(help="Enable DNS-rebinding protection and accept only these Host headers (repeatable)"),
    ] = None,
) -> None:
    """Start the knowledge MCP server."""
    from onprem_genai.knowledge.store import InMemoryStore, KnowledgeStore  # noqa: PLC0415
    from onprem_genai.mcp_server.server import build_server  # noqa: PLC0415

    g = Graph.load(graph)
    emb = make_embedder(embedder, embed_cache)
    store: KnowledgeStore
    if neo4j:
        from onprem_genai.knowledge.neo4j_store import Neo4jStore, connect  # noqa: PLC0415

        driver = connect(
            os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ["NEO4J_PASSWORD"],
        )
        store = Neo4jStore(driver, g, emb)
    else:
        store = InMemoryStore(g, emb)
    server = build_server(store)
    if transport == "stdio":
        server.run("stdio")
    else:
        import anyio  # noqa: PLC0415
        from mcp.server.transport_security import TransportSecuritySettings  # noqa: PLC0415

        security = (
            TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=allowed_host)
            if allowed_host
            else None
        )
        anyio.run(lambda: server.run_streamable_http_async(host=host, port=port, transport_security=security))
