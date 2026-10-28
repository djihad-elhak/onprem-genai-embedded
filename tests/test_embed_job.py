from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from onprem_genai.knowledge.embed_job import embed_in_subprocess, embed_with_backoff
from onprem_genai.knowledge.retrieval import CachedEmbedder, HashingEmbedder

DOCS = ["TEST(Nominal, Drop) { ASSERT_EQ(1, 1); }", "TEST(Nominal, Retry) { tester.retry(); }"]
QUERIES = ["The component shall drop frames when the link is down"]


def test_subprocess_embeddings_match_in_process(tmp_path: Path) -> None:
    emb = embed_in_subprocess(
        "hash:64", DOCS, QUERIES, tmp_path / "emb", query_instruction="retrieve tests", log=tmp_path / "e.log"
    )
    ref = HashingEmbedder(64)
    assert np.allclose(emb.embed(DOCS), ref.embed(DOCS))
    assert np.allclose(emb.embed(QUERIES, is_query=True), ref.embed(QUERIES, is_query=True))
    assert "embedded 2 documents and 1 queries" in (tmp_path / "e.log").read_text()
    with pytest.raises(LookupError, match="1 queries missing"):
        emb.embed(DOCS[:1], is_query=True)  # a document text is not a cached query


def test_subprocess_failure_reports_the_cause(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="unknown embedder spec"):
        embed_in_subprocess("bogus:1", DOCS, QUERIES, tmp_path / "emb", log=tmp_path / "e.log")
    log = (tmp_path / "e.log").read_text()
    assert log.startswith("$ ")
    assert "--embedder bogus:1" in log
    assert "Traceback" in log


class OutOfMemoryError(RuntimeError):  # same name as torch's, which the back-off recognises
    pass


class FlakyGpuEmbedder:
    name = "flaky"

    def __init__(self) -> None:
        self.batch = 16
        self.inner = HashingEmbedder(32)

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray:
        if self.batch > 4:
            raise OutOfMemoryError("CUDA out of memory. Tried to allocate 1024.00 MiB")
        return self.inner.embed(texts, is_query=is_query)


def test_backoff_halves_the_batch_until_it_fits(tmp_path: Path) -> None:
    inner = FlakyGpuEmbedder()
    cached = CachedEmbedder(inner, tmp_path)
    embed_with_backoff(cached, inner, DOCS, is_query=False)
    assert inner.batch == 4
    assert np.allclose(cached.embed(DOCS), HashingEmbedder(32).embed(DOCS))


def test_backoff_does_not_hide_other_errors(tmp_path: Path) -> None:
    class Broken(FlakyGpuEmbedder):
        def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray:
            raise ValueError("bad input")

    inner = Broken()
    with pytest.raises(ValueError, match="bad input"):
        embed_with_backoff(CachedEmbedder(inner, tmp_path), inner, DOCS, is_query=False)
    assert inner.batch == 16


FAKE_ST = '''
import hashlib
import numpy as np


class OutOfMemoryError(RuntimeError):
    pass


class SentenceTransformer:
    """Stand-in for sentence_transformers.SentenceTransformer that runs out of memory above batch 4."""

    def __init__(self, model, device=None):
        self.model, self.device, self.max_seq_length = model, device, 512

    def encode(self, texts, prompt=None, batch_size=32, normalize_embeddings=False, show_progress_bar=None):
        if batch_size > 4:
            raise OutOfMemoryError("CUDA out of memory. Tried to allocate 1024.00 MiB")
        out = []
        for t in texts:
            h = hashlib.sha256(((prompt or "") + t).encode()).digest()
            v = np.frombuffer(h, dtype=np.uint8).astype(np.float32)
            out.append(v / np.linalg.norm(v))
        return np.stack(out)
'''


def test_sentence_transformers_path_backs_off_in_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "fake"
    (fake / "sentence_transformers").mkdir(parents=True)
    (fake / "sentence_transformers" / "__init__.py").write_text(FAKE_ST)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(fake), os.environ.get("PYTHONPATH")])))
    emb = embed_in_subprocess(
        "st:Qwen/Qwen3-Embedding-0.6B",
        DOCS,
        QUERIES,
        tmp_path / "emb",
        query_instruction="retrieve tests",
        device="cuda",
        batch=16,
        log=tmp_path / "e.log",
    )
    log = (tmp_path / "e.log").read_text()
    assert "out of memory at batch 16; retrying with 8" in log
    assert "out of memory at batch 8; retrying with 4" in log
    assert "(final batch 4)" in log
    docs, queries = emb.embed(DOCS), emb.embed(QUERIES, is_query=True)
    assert docs.shape == (2, 32)
    assert queries.shape == (1, 32)
    assert not np.allclose(emb.embed(DOCS[:1]), docs[1:])  # vectors are keyed by text, not by position
