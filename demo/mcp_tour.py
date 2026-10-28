"""What an assistant sees through the knowledge MCP server: a short tour of its tools on F´.

    uv run python demo/mcp_tour.py [--graph artifacts/fprime_graph.jsonl.gz] [--pause 1.0]

The server runs in-process; the calls go through the real MCP client / server protocol (MCP SDK), as an
IDE assistant or the test-generation agent would make them.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from onprem_genai.agent.knowledge import McpToolClient
from onprem_genai.knowledge.model import Graph
from onprem_genai.knowledge.store import InMemoryStore
from onprem_genai.mcp_server.server import build_server

console = Console(width=118, highlight=False)
REQ = "SVC-COMSTUB-004"


def step(title: str, pause: float) -> None:
    time.sleep(pause)
    console.print(f"\n[bold cyan]▶ {title}[/]")


async def tour(graph: Path, pause: float) -> None:
    g = Graph.load(graph)
    async with McpToolClient(build_server(InMemoryStore(g))) as mcp:
        step("tools/list", pause)
        console.print(", ".join(await mcp.tool_names()))

        step(f'get_requirement(req_id="{REQ}")', pause)
        req = await mcp.call("get_requirement", req_id=REQ)
        console.print(f"[bold]{req['req_id']}[/] {req['text']}")
        console.print(f"verification: {req['verification']} · defined in {req['file']}:{req['line']}")
        console.print(f"tests that cite it: [red]{len(req['verified_by'])}[/]  → a traceability gap")

        step('coverage_gaps(module="Svc/ComStub")', pause)
        gaps = await mcp.call("coverage_gaps", module="Svc/ComStub")
        console.print(
            f"{len(gaps)} requirements verified 'by unit test' without a tagged test: "
            + ", ".join(x["req_id"] for x in gaps)
        )

        step(f'trace_requirement(req_id="{REQ}", k=3)', pause)
        tr = await mcp.call("trace_requirement", req_id=REQ, k=3)
        t = Table("existing test (candidate evidence)", "where", "graph", "text score", box=None)
        for s in tr["suggested_tests"]:
            t.add_row(
                s["title"].rsplit("::", 1)[-1],
                s["location"],
                s["graph_relation"],
                f"{s['text_similarity']:.2f}",
            )
        console.print(t)
        code = tr["related_code"][0]
        console.print(f"implementation: [bold]{code['title']}[/] ({code['location']})")

        step('search(query="retry sending when the driver asks for a retry", k=2)', pause)
        for hit in await mcp.call("search", query="retry sending when the driver asks for a retry", k=2):
            console.print(f"[bold]{hit['kind']}[/] {hit['title']}  [dim]{hit['location']}[/]")
            body = [
                ln for ln in hit["snippet"].splitlines()[1:] if ln.strip() and not ln.startswith("// ---")
            ]
            console.print("[dim]" + "\n".join("    " + ln[:104] for ln in body[:4]) + "[/]")
        time.sleep(pause)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", type=Path, default=Path("artifacts/fprime_graph.jsonl.gz"))
    ap.add_argument("--pause", type=float, default=1.0)
    a = ap.parse_args()
    asyncio.run(tour(a.graph, a.pause))


if __name__ == "__main__":
    main()
