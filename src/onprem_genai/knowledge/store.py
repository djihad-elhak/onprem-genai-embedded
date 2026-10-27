"""Knowledge store: graph navigation + hybrid search, behind one interface used by the MCP server.

``InMemoryStore`` serves a graph snapshot directly (laptop demo, tests, experiments). ``Neo4jStore`` answers
the same graph questions with Cypher against the deployed database. Hybrid search (BM25 + optional dense
vectors + graph boost) runs in-process in both cases over the same snapshot, so ranking behaviour is
identical whichever graph backend is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from onprem_genai.knowledge.model import EdgeType, Graph, Node, NodeType
from onprem_genai.knowledge.retrieval import BM25, Embedder, rrf
from onprem_genai.knowledge.text import tokenize
from onprem_genai.knowledge.traceability import (
    GRAPH_TIER,
    TraceDataset,
    bm25_ranker,
    build_dataset,
    graph_constrained,
    graph_scores,
)

SEARCHABLE = (NodeType.FUNCTION, NodeType.TEST_CASE, NodeType.REQUIREMENT, NodeType.DOC_CHUNK, NodeType.CLASS)
SNIPPET_CHARS = 600


@dataclass(frozen=True)
class Hit:
    id: str
    kind: str
    title: str
    location: str
    module: str | None
    score: float
    snippet: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _title(n: Node) -> str:
    p = n.props
    if n.type is NodeType.REQUIREMENT:
        return p["req_id"]
    if n.type is NodeType.DOC_CHUNK:
        return f"{p['file']} — {p['heading']}"
    return p.get("qualified") or p.get("name") or n.id


def _location(n: Node) -> str:
    p = n.props
    line = p.get("start_line") or p.get("line")
    return f"{p.get('file', '')}:{line}" if line else p.get("file", "")


def _doc_text(n: Node) -> str:
    p = n.props
    if n.type is NodeType.REQUIREMENT:
        return f"{p['req_id']} {p['text']} {p.get('rationale', '')}"
    if n.type is NodeType.DOC_CHUNK:
        return f"{p['heading']}\n{p['text']}"
    if n.type is NodeType.CLASS:
        return f"class {p['qualified']} {' '.join(p.get('bases', []))}"
    return f"{p['qualified']}\n{p.get('doc', '')}\n{p.get('text', '')}"


class KnowledgeStore(Protocol):
    def search(
        self, query: str, k: int = 10, kinds: list[str] | None = None, module: str | None = None
    ) -> list[Hit]: ...
    def get_node(self, node_id: str) -> dict[str, Any] | None: ...
    def find_symbol(self, name: str, module: str | None = None, limit: int = 10) -> list[dict[str, Any]]: ...
    def callers(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]: ...
    def callees(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]: ...
    def get_requirement(self, req_id: str) -> dict[str, Any] | None: ...
    def trace_requirement(self, req_id: str, k: int = 5) -> dict[str, Any] | None: ...
    def coverage_gaps(self, module: str | None = None) -> list[dict[str, Any]]: ...
    def modules(self) -> list[dict[str, Any]]: ...
    def module_overview(self, module: str) -> dict[str, Any] | None: ...


def _summary(n: Node, with_text: bool = False) -> dict[str, Any]:
    out = {"id": n.id, "kind": n.type.value, "title": _title(n), "location": _location(n)}
    if with_text:
        out["text"] = n.props.get("text", "")
        if n.props.get("doc"):
            out["doc"] = n.props["doc"]
    return out


class SearchIndex:
    """Hybrid lexical/dense index over searchable nodes, with optional module boost."""

    def __init__(self, g: Graph, embedder: Embedder | None = None) -> None:
        self.nodes = [n for t in SEARCHABLE for n in sorted(g.of_type(t), key=lambda x: x.id)]
        texts = [_doc_text(n) for n in self.nodes]
        self.bm25 = BM25([tokenize(t) for t in texts])
        self.embedder = embedder
        self.vectors = embedder.embed(texts) if embedder is not None else None
        self.module_of: list[str | None] = []
        for n in self.nodes:
            self.module_of.append(_module_of(g, n))

    def search(
        self, query: str, k: int, kinds: list[str] | None, module: str | None, exclude_test_code: bool = False
    ) -> list[Hit]:
        signals = [self.bm25.scores(tokenize(query))]
        if self.embedder is not None and self.vectors is not None:
            q = self.embedder.embed([query], is_query=True)[0]
            signals.append(self.vectors @ q)
        score = rrf(signals) if len(signals) > 1 else signals[0]
        if not np.any(score > 0):
            return []
        mask = np.ones(len(self.nodes), dtype=bool)
        if kinds:
            mask &= np.array([n.type.value in kinds for n in self.nodes])
        if module:
            mod_id = module if module.startswith("module:") else f"module:{module}"
            mask &= np.array([m == mod_id for m in self.module_of])
        if exclude_test_code:
            mask &= np.array([not n.props.get("is_test_code", False) for n in self.nodes])
        score = np.where(mask, score, -np.inf)
        hits = []
        for i in np.argsort(-score, kind="stable")[:k]:
            if not np.isfinite(score[i]) or score[i] <= 0:
                break
            n = self.nodes[i]
            hits.append(
                Hit(
                    n.id,
                    n.type.value,
                    _title(n),
                    _location(n),
                    self.module_of[i],
                    round(float(score[i]), 4),
                    _doc_text(n)[:SNIPPET_CHARS],
                )
            )
        return hits


def _module_of(g: Graph, n: Node) -> str | None:
    if n.type is NodeType.REQUIREMENT:
        mods = g.successors(n.id, EdgeType.ALLOCATED_TO)
    elif n.type is NodeType.DOC_CHUNK:
        mods = g.successors(n.id, EdgeType.DESCRIBES)
    else:
        files = g.predecessors(n.id, EdgeType.DEFINES)
        mods = g.predecessors(files[0].id, EdgeType.CONTAINS) if files else []
    return mods[0].id if mods else None


class InMemoryStore:
    def __init__(self, g: Graph, embedder: Embedder | None = None) -> None:
        self.g = g
        self.index = SearchIndex(g, embedder)
        self.ds: TraceDataset = build_dataset(g)
        self._trace_ranker = graph_constrained(self.ds, bm25_ranker(self.ds))

    # -------------------------------------------------------------- search & navigation
    def search(
        self, query: str, k: int = 10, kinds: list[str] | None = None, module: str | None = None
    ) -> list[Hit]:
        return self.index.search(query, k, kinds, module)

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        n = self.g.nodes.get(node_id)
        if n is None:
            return None
        return {**_summary(n), "props": n.props, "module": _module_of(self.g, n)}

    def find_symbol(self, name: str, module: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        out = []
        for t in (NodeType.FUNCTION, NodeType.TEST_CASE, NodeType.CLASS):
            for n in self.g.of_type(t):
                if n.props.get("name") == name or n.props.get("qualified", "").endswith(f"::{name}"):
                    mod = _module_of(self.g, n)
                    if module and mod != (module if module.startswith("module:") else f"module:{module}"):
                        continue
                    out.append({**_summary(n, with_text=True), "module": mod})
        return sorted(out, key=lambda d: d["id"])[:limit]

    def callers(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return [_summary(n) for n in self.g.predecessors(node_id, EdgeType.CALLS)][:limit]

    def callees(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return [_summary(n) for n in self.g.successors(node_id, EdgeType.CALLS)][:limit]

    # -------------------------------------------------------------- requirements & traceability
    def get_requirement(self, req_id: str) -> dict[str, Any] | None:
        rid = req_id if req_id.startswith("req:") else f"req:{req_id}"
        n = self.g.nodes.get(rid)
        if n is None:
            return None
        return {
            **n.props,
            "id": rid,
            "module": self.ds.req_module.get(rid),
            "verified_by": [_summary(t) for t in self.g.predecessors(rid, EdgeType.VERIFIES)],
        }

    def trace_requirement(self, req_id: str, k: int = 5) -> dict[str, Any] | None:
        req = self.get_requirement(req_id)
        if req is None:
            return None
        rid = req["id"]
        scores = self._trace_ranker(rid)
        rel = graph_scores(self.ds, rid)
        explicit = {t["id"] for t in req["verified_by"]}
        suggested = []
        for i in np.argsort(-scores, kind="stable"):
            cid = self.ds.candidates[i]
            if cid not in explicit:
                suggested.append(
                    {
                        **_summary(self.g.nodes[cid]),
                        "graph_relation": {1.0: "same-module", 0.5: "calls-into-module"}.get(
                            float(rel[i]), "none"
                        ),
                        "text_similarity": round(float(scores[i] - rel[i] * GRAPH_TIER), 4),
                    }
                )
            if len(suggested) >= k:
                break
        code = self.index.search(
            req["text"], k, [NodeType.FUNCTION.value], req["module"], exclude_test_code=True
        )
        return {
            "requirement": {key: req[key] for key in ("id", "req_id", "text", "verification", "module")},
            "explicit_tests": req["verified_by"],
            "suggested_tests": suggested,
            "related_code": [h.as_dict() for h in code],
            "status": "verified-by-tag" if explicit else "no-test-evidence",
        }

    def coverage_gaps(self, module: str | None = None) -> list[dict[str, Any]]:
        mod_id = None if module is None else (module if module.startswith("module:") else f"module:{module}")
        rows = []
        for rid in self.ds.all_requirements:
            n = self.g.nodes[rid]
            if rid in self.ds.gold or "test" not in n.props.get("verification", "").lower():
                continue
            if mod_id and self.ds.req_module[rid] != mod_id:
                continue
            rows.append(
                {
                    "req_id": n.props["req_id"],
                    "module": self.ds.req_module[rid],
                    "text": n.props["text"],
                    "verification": n.props.get("verification", ""),
                }
            )
        return rows

    # -------------------------------------------------------------- modules
    def modules(self) -> list[dict[str, Any]]:
        out = []
        for m in sorted(self.g.of_type(NodeType.MODULE), key=lambda n: n.id):
            reqs = self.g.predecessors(m.id, EdgeType.ALLOCATED_TO)
            tests = self.g.predecessors(m.id, EdgeType.TESTS)
            out.append(
                {
                    "id": m.id,
                    "files": len(self.g.successors(m.id, EdgeType.CONTAINS)),
                    "requirements": len(reqs),
                    "test_cases": len(tests),
                }
            )
        return out

    def module_overview(self, module: str) -> dict[str, Any] | None:
        mid = module if module.startswith("module:") else f"module:{module}"
        if mid not in self.g.nodes:
            return None
        files = self.g.successors(mid, EdgeType.CONTAINS)
        classes = [
            c for f in files for c in self.g.successors(f.id, EdgeType.DEFINES) if c.type is NodeType.CLASS
        ]
        reqs = self.g.predecessors(mid, EdgeType.ALLOCATED_TO)
        docs = self.g.predecessors(mid, EdgeType.DESCRIBES)
        return {
            "id": mid,
            "files": sorted(f.props["path"] for f in files),
            "classes": sorted(c.props["qualified"] for c in classes),
            "requirements": sorted(r.props["req_id"] for r in reqs),
            "test_cases": len(self.g.predecessors(mid, EdgeType.TESTS)),
            "doc_sections": sorted({d.props["heading"] for d in docs}),
            "gaps": len(self.coverage_gaps(mid)),
        }
