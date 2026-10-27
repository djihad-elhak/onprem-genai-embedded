"""Typed property graph used by the knowledge layer.

The same graph is (1) serialised as a JSONL snapshot, (2) loaded into Neo4j for the deployed platform and
(3) queried in memory for experiments and tests. Node ids are stable strings derived from source locations,
so two ingestions of the same commit produce identical snapshots.
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class NodeType(StrEnum):
    MODULE = "Module"
    FILE = "File"
    CLASS = "Class"
    FUNCTION = "Function"
    TEST_CASE = "TestCase"
    REQUIREMENT = "Requirement"
    DOC_CHUNK = "DocChunk"


class EdgeType(StrEnum):
    CONTAINS = "CONTAINS"  # Module -> File
    DEFINES = "DEFINES"  # File -> Class | Function | TestCase
    HAS_METHOD = "HAS_METHOD"  # Class -> Function
    CALLS = "CALLS"  # Function/TestCase -> Function
    INCLUDES = "INCLUDES"  # File -> File
    ALLOCATED_TO = "ALLOCATED_TO"  # Requirement -> Module
    VERIFIES = "VERIFIES"  # TestCase -> Requirement (explicit tag in test code)
    TESTS = "TESTS"  # TestCase -> Module (test lives in the module's test tree)
    DESCRIBES = "DESCRIBES"  # DocChunk -> Module


@dataclass
class Node:
    id: str
    type: NodeType
    props: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type.value, "props": self.props}


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    type: EdgeType
    props: tuple[tuple[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "type": self.type.value, "props": dict(self.props)}


class Graph:
    """In-memory multigraph with type and adjacency indexes."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self._edges: set[Edge] = set()
        self._out: dict[str, list[Edge]] = defaultdict(list)
        self._in: dict[str, list[Edge]] = defaultdict(list)
        self._by_type: dict[NodeType, list[str]] = defaultdict(list)
        self.meta: dict[str, Any] = {}

    # ------------------------------------------------------------------ mutation
    def add_node(self, node: Node) -> Node:
        existing = self.nodes.get(node.id)
        if existing is not None:
            existing.props.update(node.props)
            return existing
        self.nodes[node.id] = node
        self._by_type[node.type].append(node.id)
        return node

    def add_edge(self, src: str, dst: str, etype: EdgeType, **props: Any) -> None:
        if src not in self.nodes or dst not in self.nodes:
            raise KeyError(f"edge {etype} references unknown node: {src} -> {dst}")
        edge = Edge(src, dst, etype, tuple(sorted(props.items())))
        if edge in self._edges:
            return
        self._edges.add(edge)
        self._out[src].append(edge)
        self._in[dst].append(edge)

    # ------------------------------------------------------------------ queries
    def of_type(self, ntype: NodeType) -> list[Node]:
        return [self.nodes[i] for i in self._by_type.get(ntype, [])]

    def out_edges(self, node_id: str, etype: EdgeType | None = None) -> list[Edge]:
        return [e for e in self._out.get(node_id, []) if etype is None or e.type == etype]

    def in_edges(self, node_id: str, etype: EdgeType | None = None) -> list[Edge]:
        return [e for e in self._in.get(node_id, []) if etype is None or e.type == etype]

    def successors(self, node_id: str, etype: EdgeType | None = None) -> list[Node]:
        return [self.nodes[e.dst] for e in self.out_edges(node_id, etype)]

    def predecessors(self, node_id: str, etype: EdgeType | None = None) -> list[Node]:
        return [self.nodes[e.src] for e in self.in_edges(node_id, etype)]

    @property
    def edges(self) -> Iterator[Edge]:
        return iter(self._edges)

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {f"nodes.{t.value}": len(ids) for t, ids in sorted(self._by_type.items())}
        counts: dict[str, int] = defaultdict(int)
        for e in self._edges:
            counts[f"edges.{e.type.value}"] += 1
        out.update(sorted(counts.items()))
        return out

    # ------------------------------------------------------------------ persistence
    def save(self, path: Path) -> None:
        """Deterministic gzipped JSONL snapshot (meta line, then nodes, then edges, all sorted)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "meta", **self.meta}, sort_keys=True) + "\n")
            for nid in sorted(self.nodes):
                f.write(json.dumps({"kind": "node", **self.nodes[nid].to_json()}, sort_keys=True) + "\n")
            for e in sorted(self._edges, key=lambda e: (e.type.value, e.src, e.dst, e.props)):
                f.write(json.dumps({"kind": "edge", **e.to_json()}, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path) -> Graph:
        g = cls()
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                kind = rec.pop("kind")
                if kind == "meta":
                    g.meta = rec
                elif kind == "node":
                    g.add_node(Node(rec["id"], NodeType(rec["type"]), rec["props"]))
                elif kind == "edge":
                    g.add_edge(rec["src"], rec["dst"], EdgeType(rec["type"]), **rec["props"])
        return g

    @classmethod
    def from_parts(cls, nodes: Iterable[Node], edges: Iterable[tuple[str, str, EdgeType]]) -> Graph:
        g = cls()
        for n in nodes:
            g.add_node(n)
        for s, d, t in edges:
            g.add_edge(s, d, t)
        return g
