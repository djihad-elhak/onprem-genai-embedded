"""Contract tests: every KnowledgeStore implementation must give the same answers on the mini repository."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from onprem_genai.knowledge.model import EdgeType, Graph
from onprem_genai.knowledge.store import InMemoryStore, KnowledgeStore
from onprem_genai.mcp_server.server import build_server
from tests.conftest import neo4j_settings


@pytest.fixture(params=["memory", pytest.param("neo4j", marks=pytest.mark.neo4j)])
def store(request: pytest.FixtureRequest, mini_graph: Graph) -> Iterator[KnowledgeStore]:
    if request.param == "memory":
        yield InMemoryStore(mini_graph)
        return
    settings = neo4j_settings()
    if settings is None:
        pytest.skip("NEO4J_URI not set")
    from onprem_genai.knowledge.neo4j_store import Neo4jStore, connect, load_graph  # noqa: PLC0415

    driver = connect(*settings)
    load_graph(driver, mini_graph, wipe=True)
    try:
        yield Neo4jStore(driver, mini_graph)
    finally:
        driver.close()


def test_ingestion_links(mini_graph: Graph) -> None:
    assert "req:FOO-001" in mini_graph.nodes
    verifying = {n.props["name"] for n in mini_graph.predecessors("req:FOO-001", EdgeType.VERIFIES)}
    assert verifying == {"runNominalDispatch"}
    # F´ convention: sendCmd_DUMP in a test resolves to the component's DUMP_cmdHandler
    dump_test = next(n for n in mini_graph.nodes.values() if n.props.get("name") == "runDump")
    assert "DUMP_cmdHandler" in {c.props["name"] for c in mini_graph.successors(dump_test.id, EdgeType.CALLS)}
    # cross-module tag is still linked (and reported by the ingest audit)
    assert mini_graph.predecessors("req:BAR-001", EdgeType.VERIFIES)


def test_get_requirement(store: KnowledgeStore) -> None:
    req = store.get_requirement("FOO-002")
    assert req is not None
    assert req["module"] == "module:Svc/Foo"
    assert req["verification"] == "Unit Test"
    assert [t["title"] for t in req["verified_by"]] == ["Svc::FooTester::runQueueFullDrop"]
    assert store.get_requirement("NOPE-001") is None


def test_coverage_gaps(store: KnowledgeStore) -> None:
    gaps = store.coverage_gaps("Svc/Foo")
    assert [g["req_id"] for g in gaps] == ["FOO-004"]  # FOO-003 is verified by inspection
    assert all(g["module"] == "module:Svc/Foo" for g in store.coverage_gaps())


def test_find_symbol_and_call_graph(store: KnowledgeStore) -> None:
    syms = store.find_symbol("doDispatch")
    assert len(syms) == 1
    assert "lookupHandler" in syms[0]["text"]
    callees = {c["title"] for c in store.callees(syms[0]["id"])}
    assert callees == {"Svc::Foo::lookupHandler"}
    callers = {c["title"] for c in store.callers(syms[0]["id"])}
    assert "Svc::Foo::cmdIn_handler" in callers


def test_modules_and_overview(store: KnowledgeStore) -> None:
    mods = {m["id"]: m for m in store.modules()}
    assert mods["module:Svc/Foo"]["requirements"] == 4
    ov = store.module_overview("Svc/Foo")
    assert ov is not None
    assert ov["requirements"] == ["FOO-001", "FOO-002", "FOO-003", "FOO-004"]
    assert ov["gaps"] == 1
    assert "3 Design" in ov["doc_sections"]


def test_search_and_trace(store: KnowledgeStore) -> None:
    hits = store.search("drop commands when queue is full", k=5)
    assert hits
    assert any("FOO-002" in h.title or "Drop" in h.title or "drop" in h.title for h in hits)
    tr = store.trace_requirement("FOO-004", k=3)
    assert tr is not None
    assert tr["status"] == "no-test-evidence"
    assert tr["suggested_tests"]
    assert tr["suggested_tests"][0]["graph_relation"] == "same-module"


def _call(server: Any, name: str, args: dict[str, Any]) -> Any:
    res = asyncio.run(server.call_tool(name, args))
    assert not res.is_error, res
    return res.structured_content


def test_mcp_server_tools(mini_graph: Graph) -> None:
    server = build_server(InMemoryStore(mini_graph))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"search", "trace_requirement", "coverage_gaps", "get_symbol", "module_overview"} <= names
    gaps = _call(server, "coverage_gaps", {"module": "Svc/Foo"})
    assert [g["req_id"] for g in gaps["result"]] == ["FOO-004"]
    unknown = _call(server, "get_requirement", {"req_id": "NOPE-1"})
    assert "error" in unknown
