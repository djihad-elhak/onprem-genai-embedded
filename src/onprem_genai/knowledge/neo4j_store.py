"""Neo4j persistence: batched loader and a graph store answering navigation queries in Cypher.

Every node carries the ``:Entity`` label (unique ``id``) plus its type label
(``:Function``, ``:Requirement``...).
Labels and relationship types come from closed enums, never from user input, so they are safe to inline.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any, LiteralString, cast

from neo4j import Driver, GraphDatabase

from onprem_genai.knowledge.model import Edge, EdgeType, Graph, NodeType
from onprem_genai.knowledge.retrieval import Embedder
from onprem_genai.knowledge.store import Hit, InMemoryStore

BATCH = 2000


def connect(uri: str, user: str, password: str) -> Driver:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    return driver


def _batches(rows: list[dict[str, Any]], size: int = BATCH) -> Iterable[list[dict[str, Any]]]:
    for k in range(0, len(rows), size):
        yield rows[k : k + size]


def _clean_props(props: dict[str, Any]) -> dict[str, Any]:
    """Neo4j properties must be primitives or homogeneous lists; drop nulls and nested structures."""
    out: dict[str, Any] = {}
    for k, v in props.items():
        if v is None or isinstance(v, dict):
            continue
        out[k] = [str(x) for x in v] if isinstance(v, list | tuple) else v
    return out


def load_graph(
    driver: Driver, g: Graph, *, database: str | None = None, wipe: bool = False
) -> dict[str, int]:
    """Idempotent load (MERGE) of a graph snapshot. Returns counts written per label / relationship type."""
    counts: dict[str, int] = {}
    with driver.session(database=database) as s:
        if wipe:
            s.run("MATCH (n:Entity) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS").consume()
        s.run("CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE").consume()
        for ntype in NodeType:
            rows = [{"id": n.id, "props": _clean_props(n.props)} for n in g.of_type(ntype)]
            for batch in _batches(rows):
                # label comes from the closed NodeType enum, never from user input
                query = f"UNWIND $rows AS r MERGE (n:Entity {{id: r.id}}) SET n += r.props, n:{ntype.value}"
                s.run(
                    cast(LiteralString, query),
                    rows=batch,
                ).consume()
            counts[ntype.value] = len(rows)
        by_type: dict[EdgeType, list[Edge]] = defaultdict(list)
        for e in g.edges:
            by_type[e.type].append(e)
        for etype, edges in by_type.items():
            rows = [{"src": e.src, "dst": e.dst, "props": dict(e.props)} for e in edges]
            for batch in _batches(rows):
                # relationship type comes from the closed EdgeType enum
                query = (
                    "UNWIND $rows AS r MATCH (a:Entity {id: r.src}), (b:Entity {id: r.dst}) "
                    f"MERGE (a)-[e:{etype.value}]->(b) SET e += r.props"
                )
                s.run(
                    cast(LiteralString, query),
                    rows=batch,
                ).consume()
            counts[etype.value] = len(rows)
        s.run(
            "MERGE (m:SnapshotMeta {key: 'snapshot'}) SET m.source = $source, m.commit = $commit",
            source=g.meta.get("source"),
            commit=g.meta.get("commit"),
        ).consume()
    return counts


def _summary_from_record(n: dict[str, Any], labels: list[str]) -> dict[str, Any]:
    kind = next((lbl for lbl in labels if lbl != "Entity"), "Entity")
    if kind == "Requirement":
        title = n.get("req_id")
    elif kind == "DocChunk":
        title = f"{n.get('file')} — {n.get('heading')}"
    else:
        title = n.get("qualified") or n.get("name") or n.get("id")
    line = n.get("start_line") or n.get("line")
    loc = f"{n.get('file', '')}:{line}" if line else n.get("file", "")
    return {"id": n["id"], "kind": kind, "title": title, "location": loc}


class Neo4jStore:
    """Graph navigation in Neo4j; ranking (search, trace suggestions) delegated to the in-process index
    built from the same snapshot, so results are identical to :class:`InMemoryStore`."""

    def __init__(
        self, driver: Driver, snapshot: Graph, embedder: Embedder | None = None, database: str | None = None
    ) -> None:
        self.driver, self.database = driver, database
        self.ranking = InMemoryStore(snapshot, embedder)

    def _q(self, cypher: LiteralString, **params: Any) -> list[dict[str, Any]]:
        with self.driver.session(database=self.database) as s:
            return [r.data() for r in s.run(cypher, **params)]

    @staticmethod
    def _mod(module: str | None) -> str | None:
        if module is None:
            return None
        return module if module.startswith("module:") else f"module:{module}"

    # -------------------------------------------------------------- ranking (in-process)
    def search(
        self, query: str, k: int = 10, kinds: list[str] | None = None, module: str | None = None
    ) -> list[Hit]:
        return self.ranking.search(query, k, kinds, module)

    def trace_requirement(self, req_id: str, k: int = 5) -> dict[str, Any] | None:
        return self.ranking.trace_requirement(req_id, k)

    # -------------------------------------------------------------- graph navigation (Cypher)
    def get_node(self, node_id: str) -> dict[str, Any] | None:
        rows = self._q(
            "MATCH (n:Entity {id: $id}) "
            "OPTIONAL MATCH (n)<-[:DEFINES]-(:File)<-[:CONTAINS]-(m1:Module) "
            "OPTIONAL MATCH (n)-[:ALLOCATED_TO|DESCRIBES]->(m2:Module) "
            "RETURN n {.*} AS n, labels(n) AS labels, coalesce(m1.id, m2.id) AS module",
            id=node_id,
        )
        if not rows:
            return None
        r = rows[0]
        return {**_summary_from_record(r["n"], r["labels"]), "props": r["n"], "module": r["module"]}

    def find_symbol(self, name: str, module: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._q(
            "MATCH (m:Module)-[:CONTAINS]->(:File)-[:DEFINES]->(n) "
            "WHERE (n:Function OR n:TestCase OR n:Class) "
            "AND (n.name = $name OR n.qualified ENDS WITH $suffix) "
            "AND ($module IS NULL OR m.id = $module) "
            "RETURN n {.*} AS n, labels(n) AS labels, m.id AS module ORDER BY n.id LIMIT $limit",
            name=name,
            suffix=f"::{name}",
            module=self._mod(module),
            limit=limit,
        )
        out = []
        for r in rows:
            d = {
                **_summary_from_record(r["n"], r["labels"]),
                "text": r["n"].get("text", ""),
                "module": r["module"],
            }
            if r["n"].get("doc"):
                d["doc"] = r["n"]["doc"]
            out.append(d)
        return out

    def callers(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._q(
            "MATCH (c)-[:CALLS]->(:Entity {id: $id}) RETURN c {.*} AS n, labels(c) AS labels "
            "ORDER BY c.id LIMIT $limit",
            id=node_id,
            limit=limit,
        )
        return [_summary_from_record(r["n"], r["labels"]) for r in rows]

    def callees(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._q(
            "MATCH (:Entity {id: $id})-[:CALLS]->(c) RETURN c {.*} AS n, labels(c) AS labels "
            "ORDER BY c.id LIMIT $limit",
            id=node_id,
            limit=limit,
        )
        return [_summary_from_record(r["n"], r["labels"]) for r in rows]

    def get_requirement(self, req_id: str) -> dict[str, Any] | None:
        rid = req_id if req_id.startswith("req:") else f"req:{req_id}"
        rows = self._q(
            "MATCH (r:Requirement {id: $id})-[:ALLOCATED_TO]->(m:Module) "
            "OPTIONAL MATCH (t:TestCase)-[:VERIFIES]->(r) "
            "WITH r, m, t ORDER BY t.id "
            "RETURN r {.*} AS r, m.id AS module, "
            "collect(CASE WHEN t IS NULL THEN NULL ELSE t {.*} END) AS tests",
            id=rid,
        )
        if not rows:
            return None
        r = rows[0]
        return {
            **r["r"],
            "id": rid,
            "module": r["module"],
            "verified_by": [_summary_from_record(t, ["TestCase"]) for t in r["tests"]],
        }

    def coverage_gaps(self, module: str | None = None) -> list[dict[str, Any]]:
        rows = self._q(
            "MATCH (r:Requirement)-[:ALLOCATED_TO]->(m:Module) "
            "WHERE toLower(coalesce(r.verification, '')) CONTAINS 'test' "
            "AND NOT EXISTS { MATCH (:TestCase)-[:VERIFIES]->(r) } "
            "AND ($module IS NULL OR m.id = $module) "
            "RETURN r.req_id AS req_id, m.id AS module, r.text AS text, r.verification AS verification "
            "ORDER BY r.id",
            module=self._mod(module),
        )
        return rows

    def modules(self) -> list[dict[str, Any]]:
        return self._q(
            "MATCH (m:Module) "
            "RETURN m.id AS id, "
            "COUNT { (m)-[:CONTAINS]->(:File) } AS files, "
            "COUNT { (:Requirement)-[:ALLOCATED_TO]->(m) } AS requirements, "
            "COUNT { (:TestCase)-[:TESTS]->(m) } AS test_cases ORDER BY id"
        )

    def module_overview(self, module: str) -> dict[str, Any] | None:
        mid = self._mod(module)
        rows = self._q(
            "MATCH (m:Module {id: $id}) "
            "RETURN m.id AS id, "
            "[(m)-[:CONTAINS]->(f:File) | f.path] AS files, "
            "[(m)-[:CONTAINS]->(:File)-[:DEFINES]->(c:Class) | c.qualified] AS classes, "
            "[(r:Requirement)-[:ALLOCATED_TO]->(m) | r.req_id] AS requirements, "
            "COUNT { (:TestCase)-[:TESTS]->(m) } AS test_cases, "
            "[(d:DocChunk)-[:DESCRIBES]->(m) | d.heading] AS doc_sections",
            id=mid,
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r["id"],
            "files": sorted(r["files"]),
            "classes": sorted(r["classes"]),
            "requirements": sorted(r["requirements"]),
            "test_cases": r["test_cases"],
            "doc_sections": sorted(set(r["doc_sections"])),
            "gaps": len(self.coverage_gaps(mid)),
        }
