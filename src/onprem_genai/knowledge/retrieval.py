"""Retrieval primitives: BM25, dense embeddings and rank fusion.

Everything here is dependency-light (numpy only). Embedding backends are pluggable: an OpenAI-compatible
``/v1/embeddings`` endpoint (llama.cpp, vLLM, TEI — i.e. the same on-prem serving stack), a local
sentence-transformers model, or a deterministic hashing embedder used only in tests.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

import httpx
import numpy as np

from onprem_genai.knowledge.text import tokenize


class BM25:
    """Okapi BM25 over pre-tokenised documents."""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.n_docs = len(docs)
        self.doc_len = np.array([len(d) for d in docs], dtype=np.float64)
        self.avgdl = float(self.doc_len.mean()) if self.n_docs else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, doc in enumerate(docs):
            for term, tf in Counter(doc).items():
                self.postings[term].append((i, tf))
        self.idf = {
            t: math.log(1.0 + (self.n_docs - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()
        }

    def scores(self, query: Sequence[str]) -> np.ndarray:
        out = np.zeros(self.n_docs, dtype=np.float64)
        norm = self.k1 * (1.0 - self.b + self.b * self.doc_len / (self.avgdl or 1.0))
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in self.postings[term]:
                out[i] += idf * tf * (self.k1 + 1.0) / (tf + norm[i])
        return out


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray: ...


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1.0, norms)


class HashingEmbedder:
    """Deterministic feature-hashing 'embedding' of code tokens. Lexical, not semantic: tests only."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.name = f"hashing-{dim}"

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray:
        m = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in tokenize(t):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
                m[i, h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        return _normalize(m)


class OpenAIEmbedder:
    """Any OpenAI-compatible embeddings endpoint (llama.cpp ``--embedding``, vLLM, TEI...)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        query_instruction: str | None = None,
        batch: int = 32,
        api_key: str | None = None,
    ) -> None:
        self.base_url, self.model, self.batch = base_url.rstrip("/"), model, batch
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.query_instruction = query_instruction
        self.name = f"openai:{model}"

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray:
        prefix = (
            f"Instruct: {self.query_instruction}\nQuery: " if (is_query and self.query_instruction) else ""
        )
        out: list[list[float]] = []
        with httpx.Client(timeout=300, headers=self.headers) as client:
            for k in range(0, len(texts), self.batch):
                chunk = [prefix + t for t in texts[k : k + self.batch]]
                r = client.post(f"{self.base_url}/v1/embeddings", json={"model": self.model, "input": chunk})
                r.raise_for_status()
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                out.extend(d["embedding"] for d in data)
        return _normalize(np.asarray(out, dtype=np.float32))


class SentenceTransformerEmbedder:
    """Local sentence-transformers model (e.g. Qwen/Qwen3-Embedding-0.6B); optional dependency."""

    def __init__(
        self,
        model: str,
        query_instruction: str | None = None,
        device: str | None = None,
        max_seq_length: int = 2048,
        batch: int = 16,
    ) -> None:
        from sentence_transformers import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
            SentenceTransformer,
        )

        self.st: Any = SentenceTransformer(model, device=device)
        self.st.max_seq_length = max_seq_length
        self.query_instruction, self.batch = query_instruction, batch
        self.name = f"st:{model}"

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray:
        prompt = (
            f"Instruct: {self.query_instruction}\nQuery: " if (is_query and self.query_instruction) else None
        )
        emb = self.st.encode(
            list(texts),
            prompt=prompt,
            batch_size=self.batch,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(emb, dtype=np.float32)


class CachedEmbedder:
    """Disk cache keyed by (embedder name, text hash) so experiments can be re-run offline."""

    def __init__(self, inner: Embedder, cache_dir: Path) -> None:
        self.inner, self.name = inner, inner.name
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, text: str, is_query: bool) -> str:
        h = hashlib.sha256(f"{self.name}|{int(is_query)}|{text}".encode()).hexdigest()
        return h[:32]

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray:
        keys = [self._key(t, is_query) for t in texts]
        store = self.cache_dir / "embeddings.npz"
        cache: dict[str, np.ndarray] = dict(np.load(store)) if store.exists() else {}
        missing = [i for i, k in enumerate(keys) if k not in cache]
        if missing:
            new = self.inner.embed([texts[i] for i in missing], is_query=is_query)
            for i, vec in zip(missing, new, strict=True):
                cache[keys[i]] = vec
            np.savez_compressed(store, **cast(dict[str, Any], cache))
        return np.stack([cache[k] for k in keys]) if keys else np.zeros((0, 0), dtype=np.float32)


def cosine_scores(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return matrix @ query_vec


def rrf(
    rankings: Sequence[np.ndarray], k: float = 60.0, weights: Sequence[float] | None = None
) -> np.ndarray:
    """Reciprocal rank fusion of score vectors (higher is better) over the same candidate set."""
    n = len(rankings[0])
    fused = np.zeros(n, dtype=np.float64)
    for w, scores in zip(weights or [1.0] * len(rankings), rankings, strict=True):
        order = np.argsort(-scores, kind="stable")
        ranks = np.empty(n, dtype=np.float64)
        ranks[order] = np.arange(1, n + 1)
        fused += w / (k + ranks)
    return fused


ScoreFn = Callable[[str], np.ndarray]
