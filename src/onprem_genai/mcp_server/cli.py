"""`oge mcp serve` — start the knowledge MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from onprem_genai.knowledge.model import Graph

app = typer.Typer(help="Model Context Protocol servers.", no_args_is_help=True)


@app.command("serve")
def serve(
    graph: Annotated[Path, typer.Option(help="Graph snapshot")] = Path("artifacts/fprime_graph.jsonl.gz"),
    transport: Annotated[str, typer.Option(help="stdio | streamable-http")] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    embedder: Annotated[str, typer.Option(help="none | st:<model> | openai:<url>@<model>")] = "none",
    neo4j_uri: Annotated[
        str | None, typer.Option(envvar="NEO4J_URI", help="Use Neo4j for graph queries")
    ] = None,
    neo4j_user: str = typer.Option("neo4j", envvar="NEO4J_USER"),
    neo4j_password: str = typer.Option("", envvar="NEO4J_PASSWORD"),
) -> None:
    from onprem_genai.knowledge.cli import make_embedder  # noqa: PLC0415
    from onprem_genai.knowledge.store import InMemoryStore, KnowledgeStore  # noqa: PLC0415
    from onprem_genai.mcp_server.server import build_server  # noqa: PLC0415

    snapshot = Graph.load(graph)
    emb = make_embedder(embedder, Path("artifacts/embedding_cache"))
    store: KnowledgeStore
    if neo4j_uri:
        from onprem_genai.knowledge.neo4j_store import Neo4jStore, connect  # noqa: PLC0415

        store = Neo4jStore(connect(neo4j_uri, neo4j_user, neo4j_password), snapshot, emb)
    else:
        store = InMemoryStore(snapshot, emb)
    server = build_server(store)
    if transport == "stdio":
        server.run("stdio")
    elif transport == "streamable-http":
        server.run("streamable-http", host=host, port=port)
    else:
        raise typer.BadParameter("transport must be stdio or streamable-http")
