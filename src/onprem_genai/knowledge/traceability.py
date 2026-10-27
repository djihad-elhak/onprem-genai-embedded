"""Requirement -> test traceability recovery: dataset, rankers, metrics and gap analysis.

Ground truth comes from explicit ``REQUIREMENT("ID")`` tags in F´ unit tests. For evaluation these tags (and
any occurrence of a requirement ID) are masked from the test code, and each method must rank all test cases
of the code base for every tagged requirement.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import httpx
import numpy as np

from onprem_genai.knowledge.model import EdgeType, Graph, NodeType
from onprem_genai.knowledge.retrieval import BM25, Embedder, rrf
from onprem_genai.knowledge.text import split_identifier, tokenize

_TAG = re.compile(r'REQUIREMENT\s*\(\s*"[^"]*"\s*\)\s*;?')
_ID_LIKE = re.compile(r"\b[A-Z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*-\d{2,4}[a-z]?\b")
GRAPH_TIER = 1e6
QUERY_INSTRUCTION = "Given a software requirement, retrieve the unit test code that verifies it"


@dataclass
class TraceDataset:
    req_ids: list[str]
    req_text: dict[str, str]
    req_module: dict[str, str]
    candidates: list[str]
    cand_text: list[str]
    cand_module: list[str]
    cand_called_modules: list[set[str]]
    gold: dict[str, set[int]]
    all_requirements: list[str] = field(default_factory=list)


def mask_test_text(text: str) -> str:
    return _ID_LIKE.sub(" ", _TAG.sub(" ", text))


def candidate_text(props: dict[str, Any]) -> str:
    name_words = " ".join(split_identifier(props["name"].replace(".", "_")))
    return "\n".join(
        [
            f"{props['qualified']} ({name_words})",
            f"file: {props['file']}",
            props.get("doc", ""),
            mask_test_text(props.get("text", "")),
        ]
    )


def build_dataset(g: Graph) -> TraceDataset:
    tests = sorted(g.of_type(NodeType.TEST_CASE), key=lambda n: n.id)
    index = {t.id: i for i, t in enumerate(tests)}
    module_of_fn: dict[str, str] = {}
    for mod in g.of_type(NodeType.MODULE):
        for f in g.successors(mod.id, EdgeType.CONTAINS):
            for d in g.successors(f.id, EdgeType.DEFINES):
                module_of_fn[d.id] = mod.id
    cand_module = [g.successors(t.id, EdgeType.TESTS)[0].id for t in tests]
    called = [
        {module_of_fn[c.id] for c in g.successors(t.id, EdgeType.CALLS) if c.id in module_of_fn}
        for t in tests
    ]

    reqs = sorted(g.of_type(NodeType.REQUIREMENT), key=lambda n: n.id)
    gold: dict[str, set[int]] = {}
    for r in reqs:
        linked = {index[e.src] for e in g.in_edges(r.id, EdgeType.VERIFIES) if e.src in index}
        if linked:
            gold[r.id] = linked
    return TraceDataset(
        req_ids=sorted(gold),
        req_text={r.id: r.props["text"] for r in reqs},
        req_module={r.id: g.successors(r.id, EdgeType.ALLOCATED_TO)[0].id for r in reqs},
        candidates=[t.id for t in tests],
        cand_text=[candidate_text(t.props) for t in tests],
        cand_module=cand_module,
        cand_called_modules=called,
        gold=gold,
        all_requirements=[r.id for r in reqs],
    )


# ------------------------------------------------------------------------------------------- rankers
Ranker = Callable[[str], np.ndarray]


def bm25_ranker(ds: TraceDataset) -> Ranker:
    index = BM25([tokenize(t) for t in ds.cand_text])
    return lambda rid: index.scores(tokenize(ds.req_text[rid]))


def graph_scores(ds: TraceDataset, rid: str) -> np.ndarray:
    """Structural prior only: tests of the requirement's module, then tests calling into that module."""
    mod = ds.req_module[rid]
    return np.array(
        [
            1.0 if m == mod else (0.5 if mod in called else 0.0)
            for m, called in zip(ds.cand_module, ds.cand_called_modules, strict=True)
        ]
    )


def graph_ranker(ds: TraceDataset) -> Ranker:
    return lambda rid: graph_scores(ds, rid)


def dense_ranker(ds: TraceDataset, embedder: Embedder) -> Ranker:
    docs = embedder.embed(ds.cand_text)
    queries = embedder.embed([ds.req_text[r] for r in ds.req_ids], is_query=True)
    qmap = dict(zip(ds.req_ids, queries, strict=True))
    return lambda rid: docs @ qmap[rid]


def graph_constrained(ds: TraceDataset, inner: Ranker) -> Ranker:
    """Rank by graph tier first, then by the inner (lexical / dense / fused) score within each tier."""

    def rank(rid: str) -> np.ndarray:
        s = inner(rid)
        span = float(s.max() - s.min()) or 1.0
        return graph_scores(ds, rid) * GRAPH_TIER + (s - s.min()) / span

    return rank


def fused(rankers: Sequence[Ranker]) -> Ranker:
    return lambda rid: rrf([r(rid) for r in rankers])


class LlmJudge:
    """Scores (requirement, test) pairs 0-10 with any OpenAI-compatible chat endpoint."""

    PROMPT = (
        "You are auditing requirements traceability for flight software.\n"
        "Requirement:\n{req}\n\nUnit test code:\n```cpp\n{code}\n```\n\n"
        "Does this test verify the requirement (exercise the required behaviour and check its outcome)? "
        "Answer with a single integer from 0 (unrelated) to 10 (directly verifies it)."
    )

    def __init__(
        self,
        base_url: str,
        model: str = "default",
        max_code_chars: int = 3500,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.base_url, self.model, self.max_code_chars = base_url.rstrip("/"), model, max_code_chars
        self.extra_body = extra_body or {}
        self.client = httpx.Client(timeout=300)

    def score(self, req_text: str, code: str) -> float:
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": self.PROMPT.format(req=req_text, code=code[: self.max_code_chars]),
                }
            ],
            "max_tokens": 8,
            "temperature": 0.0,
            **self.extra_body,
        }
        r = self.client.post(f"{self.base_url}/v1/chat/completions", json=body)
        r.raise_for_status()
        m = re.search(r"\d+", r.json()["choices"][0]["message"]["content"] or "")
        return min(float(m.group()), 10.0) if m else 0.0


def llm_reranked(
    ds: TraceDataset, base: Ranker, judge: LlmJudge, top_n: int = 10, max_workers: int = 8
) -> Ranker:
    """Rerank the head of ``base`` with LLM relevance scores (concurrent requests, memoised per requirement).

    Within the head, ties on the LLM score keep the base order; everything below the head keeps its order.
    """
    cache: dict[str, np.ndarray] = {}

    def rank(rid: str) -> np.ndarray:
        if rid in cache:
            return cache[rid]
        s = base(rid).astype(np.float64)
        top = [int(i) for i in np.argsort(-s, kind="stable")[:top_n]]
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            scores = list(pool.map(lambda i: judge.score(ds.req_text[rid], ds.cand_text[i]), top))
        out = s - s.max() - 1.0
        for pos, (i, llm) in enumerate(zip(top, scores, strict=True)):
            out[i] = 100.0 * llm + (top_n - pos) * 1e-3
        cache[rid] = out
        return out

    return rank


# ------------------------------------------------------------------------------------------- metrics
def ranking_metrics(scores: np.ndarray, gold: set[int], ks: Sequence[int] = (1, 5, 10)) -> dict[str, float]:
    order = np.argsort(-scores, kind="stable")
    ranks = np.empty(len(scores), dtype=np.int64)
    ranks[order] = np.arange(1, len(scores) + 1)
    gold_ranks = sorted(int(ranks[i]) for i in gold)
    ap = sum((k + 1) / r for k, r in enumerate(gold_ranks)) / len(gold)
    out = {"ap": ap, "rr": 1.0 / gold_ranks[0]}
    for k in ks:
        out[f"recall@{k}"] = sum(r <= k for r in gold_ranks) / len(gold)
    dcg = sum(1.0 / np.log2(r + 1) for r in gold_ranks if r <= 10)
    idcg = sum(1.0 / np.log2(i + 2) for i in range(min(len(gold), 10)))
    out["ndcg@10"] = dcg / idcg
    return out


def evaluate(
    ds: TraceDataset, ranker: Ranker, *, tie_seeds: int = 10, bootstrap: int = 1000, seed: int = 0
) -> dict[str, Any]:
    """Mean metrics over requirements. Ties are broken randomly and averaged over ``tie_seeds`` draws."""
    rng = np.random.default_rng(seed)
    per_req: dict[str, dict[str, float]] = {}
    for rid in ds.req_ids:
        s = ranker(rid).astype(np.float64)
        draws = []
        for _ in range(tie_seeds):
            noise = rng.random(len(s)) * 1e-9 * (np.abs(s).max() or 1.0)
            draws.append(ranking_metrics(s + noise, ds.gold[rid]))
        per_req[rid] = {k: float(np.mean([d[k] for d in draws])) for k in draws[0]}
    names = list(next(iter(per_req.values())))
    matrix = np.array([[per_req[r][k] for k in names] for r in ds.req_ids])
    means = matrix.mean(axis=0)
    boots = np.array(
        [matrix[rng.integers(0, len(matrix), len(matrix))].mean(axis=0) for _ in range(bootstrap)]
    )
    lo, hi = np.percentile(boots, [2.5, 97.5], axis=0)
    return {
        "n_requirements": len(ds.req_ids),
        "n_candidates": len(ds.candidates),
        "metrics": {
            k: {"mean": round(float(m), 4), "ci95": [round(float(a), 4), round(float(b), 4)]}
            for k, m, a, b in zip(names, means, lo, hi, strict=True)
        },
        "per_requirement": per_req,
    }


# ------------------------------------------------------------------------------------------- gap analysis
def gap_report(
    g: Graph, ds: TraceDataset, ranker: Ranker | None = None, top_k: int = 3
) -> list[dict[str, Any]]:
    """Requirements whose verification method includes testing but which no test explicitly tags."""
    rows = []
    for rid in ds.all_requirements:
        node = g.nodes[rid]
        method = node.props.get("verification", "").lower()
        if "test" not in method or rid in ds.gold:
            continue
        row: dict[str, Any] = {
            "requirement": node.props["req_id"],
            "module": ds.req_module[rid],
            "verification": node.props.get("verification", ""),
            "text": node.props["text"],
        }
        if ranker is not None:
            s = ranker(rid)
            row["suggested_tests"] = [ds.candidates[i] for i in np.argsort(-s, kind="stable")[:top_k]]
        rows.append(row)
    return rows


def audit_findings(report_tags_undefined: list[str], report_tags_cross: list[str]) -> dict[str, Any]:
    undefined = sorted({u.split(" @")[0] for u in report_tags_undefined})
    cross = sorted({c.split(" tagged")[0] for c in report_tags_cross})
    return {"tags_to_undefined_requirements": undefined, "tags_to_other_modules_requirements": cross}


def save_json(obj: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
