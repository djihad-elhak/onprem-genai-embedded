from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from onprem_genai.knowledge import traceability as tr
from onprem_genai.knowledge.model import Graph
from onprem_genai.knowledge.retrieval import BM25, CachedEmbedder, HashingEmbedder, rrf
from onprem_genai.knowledge.text import split_identifier, tokenize


def test_identifier_splitting_and_tokenize() -> None:
    assert split_identifier("runNominalDispatch") == ["run", "nominal", "dispatch"]
    assert split_identifier("CMD_NO_OP") == ["cmd", "no", "op"]
    assert split_identifier("parseHTTPResponse") == ["parse", "http", "response"]
    toks = tokenize("The component shall drop commands when queues are full")
    assert "drop" in toks
    assert "command" in toks
    assert "queue" in toks
    assert "the" not in toks


def test_bm25_prefers_matching_document() -> None:
    docs = [tokenize(t) for t in ("drop command queue full", "telemetry channel update", "command dispatch")]
    s = BM25(docs).scores(tokenize("drop full queue"))
    assert int(np.argmax(s)) == 0
    assert s[1] == 0.0


def test_rrf() -> None:
    a = np.array([3.0, 2.0, 1.0])
    b = np.array([1.0, 2.0, 3.0])
    fused = rrf([a, b])
    assert fused[0] == pytest.approx(fused[2])  # ranks (1,3) and (3,1) are symmetric
    assert int(np.argmax(rrf([a, a]))) == 0


def test_hashing_and_cached_embedder(tmp_path: Path) -> None:
    emb = HashingEmbedder(64)
    m = emb.embed(["drop command", "drop command", "telemetry"])
    assert m.shape == (3, 64)
    assert m[0] @ m[1] == pytest.approx(1.0)
    cached = CachedEmbedder(emb, tmp_path)
    first = cached.embed(["a b", "c d"])
    second = cached.embed(["c d", "a b"])
    assert np.allclose(first[0], second[1])
    assert (tmp_path / "embeddings.npz").exists()


def test_ranking_metrics_hand_computed() -> None:
    scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5])  # ranks 1..5
    m = tr.ranking_metrics(scores, {1, 3})  # gold at ranks 2 and 4
    assert m["ap"] == pytest.approx((1 / 2 + 2 / 4) / 2)
    assert m["rr"] == pytest.approx(0.5)
    assert m["recall@1"] == 0.0
    assert m["recall@5"] == 1.0
    idcg = 1 + 1 / np.log2(3)
    assert m["ndcg@10"] == pytest.approx((1 / np.log2(3) + 1 / np.log2(5)) / idcg)


def test_masking_removes_tags_and_ids() -> None:
    text = 'void t() {\n  REQUIREMENT("CD-001");\n  // verifies HS-1001 too\n  run();\n}'
    masked = tr.mask_test_text(text)
    assert "CD-001" not in masked
    assert "HS-1001" not in masked
    assert "REQUIREMENT" not in masked
    assert "run();" in masked


def test_dataset_and_rankers_on_mini_repo(mini_graph: Graph) -> None:
    ds = tr.build_dataset(mini_graph)
    assert set(ds.req_ids) == {"req:FOO-001", "req:FOO-002", "req:BAR-001"}
    assert all("REQUIREMENT" not in t for t in ds.cand_text)
    hybrid = tr.graph_constrained(ds, tr.bm25_ranker(ds))
    res = tr.evaluate(ds, hybrid, tie_seeds=3, bootstrap=50)
    assert res["n_requirements"] == 3
    assert 0.0 < res["metrics"]["ap"]["mean"] <= 1.0
    # FOO-002 ("drop ... queue is full") must rank runQueueFullDrop first under the hybrid ranker
    s = hybrid("req:FOO-002")
    best = ds.candidates[int(np.argmax(s))]
    assert "runQueueFullDrop" in best
    dense = tr.graph_constrained(ds, tr.dense_ranker(ds, HashingEmbedder(256)))
    assert tr.evaluate(ds, dense, tie_seeds=2, bootstrap=20)["n_requirements"] == 3


def test_gap_report(mini_graph: Graph) -> None:
    ds = tr.build_dataset(mini_graph)
    gaps = tr.gap_report(mini_graph, ds, tr.bm25_ranker(ds), top_k=2)
    assert [g["requirement"] for g in gaps] == ["FOO-004"]
    assert len(gaps[0]["suggested_tests"]) == 2


def test_llm_rerank_uses_judge(mini_graph: Graph) -> None:
    ds = tr.build_dataset(mini_graph)

    class FakeJudge:
        def score(self, req_text: str, code: str) -> float:
            return 10.0 if "runDump" in code else 0.0

    ranker = tr.llm_reranked(ds, tr.bm25_ranker(ds), FakeJudge(), top_n=len(ds.candidates))  # type: ignore[arg-type]
    s = ranker("req:FOO-001")
    assert "runDump" in ds.candidates[int(np.argmax(s))]
