"""Requirement catalog: every requirement of the knowledge graph with its traceability state.

Base state from the graph: ``covered`` (a test cites it), ``gap`` (its verification method includes testing
but no test cites it) or ``not_by_test`` (verified by inspection or analysis only). The console overlays what
the agent and the reviewers did: ``generated`` (a verified test awaits review), ``accepted`` (a reviewer
judged it relevant or partial), ``rejected`` (judged not relevant) and ``attempted`` (the agent tried and
failed).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from onprem_genai.knowledge.model import EdgeType, NodeType
from onprem_genai.knowledge.store import InMemoryStore

BASE_STATES = ("covered", "gap", "not_by_test")
STATES = ("covered", "accepted", "generated", "attempted", "rejected", "gap", "not_by_test")


@dataclass(frozen=True)
class Requirement:
    req_id: str
    module: str
    text: str
    verification: str
    file: str
    line: int
    rationale: str
    tagged_tests: int
    base: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "req_id": self.req_id,
            "module": self.module,
            "text": self.text,
            "verification": self.verification,
            "file": self.file,
            "line": self.line,
            "rationale": self.rationale,
            "tagged_tests": self.tagged_tests,
            "base": self.base,
        }


class Catalog:
    def __init__(self, store: InMemoryStore, fprime: Path | None) -> None:
        g = store.g
        self.store = store
        self.fprime = fprime
        self.items: dict[str, Requirement] = {}
        for n in sorted(g.of_type(NodeType.REQUIREMENT), key=lambda x: x.props.get("req_id", x.id)):
            p = n.props
            tagged = len(g.predecessors(n.id, EdgeType.VERIFIES))
            verification = str(p.get("verification", ""))
            if tagged:
                base = "covered"
            elif "test" in verification.lower():
                base = "gap"
            else:
                base = "not_by_test"
            module = store.ds.req_module.get(n.id, "").removeprefix("module:")
            self.items[p["req_id"]] = Requirement(
                req_id=p["req_id"],
                module=module,
                text=" ".join(str(p.get("text", "")).split()),
                verification=verification,
                file=str(p.get("file", "")),
                line=int(p.get("line", 0) or 0),
                rationale=" ".join(str(p.get("rationale", "")).split()),
                tagged_tests=tagged,
                base=base,
            )
        self._supported: dict[str, str | None] = {}

    def agent_support(self, module: str) -> str | None:
        """None when the agent can work on the module's tests, else the reason it cannot."""
        if module not in self._supported:
            if self.fprime is None:
                self._supported[module] = "no F´ workspace is configured"
            else:
                from onprem_genai.agent.fprime import (  # noqa: PLC0415  (keeps the console importable without the agent extra)
                    UnsupportedComponentError,
                    find_component,
                )

                try:
                    find_component(self.fprime, module)
                    self._supported[module] = None
                except (UnsupportedComponentError, OSError) as exc:
                    self._supported[module] = str(exc)
        return self._supported[module]


def overlay_state(base: str, results: list[dict[str, Any]]) -> str:
    """Display state from the graph state and the console's results for one requirement (newest first)."""
    if base == "covered":
        return "covered"
    passed = [r for r in results if r["status"] == "passed"]
    if any(r.get("verdict") in ("relevant", "partial") for r in passed):
        return "accepted"
    if any(r.get("verdict") is None for r in passed):
        return "generated"
    if passed:
        return "rejected"
    if results:
        return "attempted"
    return base
