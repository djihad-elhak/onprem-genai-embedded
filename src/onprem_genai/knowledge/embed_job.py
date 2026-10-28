"""Compute embeddings in a child process: ``python -m onprem_genai.knowledge.embed_job``.

A GPU model loaded in a long-lived process (a notebook kernel, a server) keeps its device memory until that
process exits, and after an out-of-memory error PyTorch's allocator can hold most of the device. On a shared
GPU host that starves whatever starts next (in the Kaggle benchmark: every LLM server). Running the embedding
pass in a child process returns all of its memory, whatever happens, and the parent reads the vectors from the
:class:`~onprem_genai.knowledge.retrieval.CachedEmbedder` cache the child filled.

Batches shrink on out-of-memory errors (halving down to 1) instead of failing the pass.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from onprem_genai.knowledge.retrieval import CachedEmbedder, CacheOnlyEmbedder, Embedder, HashingEmbedder

REQUEST_FILE = "request.json"


def make_inner(
    spec: str,
    *,
    query_instruction: str | None,
    device: str | None,
    max_seq_length: int,
    batch: int,
) -> Embedder:
    """``st:<hf-model>`` (sentence-transformers) or ``hash:<dim>`` (deterministic, tests only)."""
    if spec.startswith("st:"):
        from onprem_genai.knowledge.retrieval import SentenceTransformerEmbedder  # noqa: PLC0415

        return SentenceTransformerEmbedder(
            spec.removeprefix("st:"),
            query_instruction=query_instruction,
            device=device,
            max_seq_length=max_seq_length,
            batch=batch,
        )
    if spec.startswith("hash:"):
        return HashingEmbedder(int(spec.removeprefix("hash:")))
    raise ValueError(f"unknown embedder spec {spec!r} (expected st:<model> or hash:<dim>)")


def embedder_name(spec: str) -> str:
    """The name the child's embedder reports, i.e. the key prefix of its cache entries."""
    if spec.startswith("st:"):
        return spec  # SentenceTransformerEmbedder.name == "st:<model>"
    if spec.startswith("hash:"):
        return f"hashing-{int(spec.removeprefix('hash:'))}"
    raise ValueError(f"unknown embedder spec {spec!r} (expected st:<model> or hash:<dim>)")


def _is_oom(exc: BaseException) -> bool:
    return type(exc).__name__ == "OutOfMemoryError" or "out of memory" in str(exc).lower()


def _release_cuda_cache() -> None:
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def embed_with_backoff(
    cached: CachedEmbedder, inner: Any, texts: Sequence[str], *, is_query: bool, log: Any = None
) -> None:
    """Fill the cache for ``texts``; on out-of-memory, halve ``inner.batch`` and retry (down to 1)."""
    while True:
        try:
            cached.embed(texts, is_query=is_query)
            return
        except Exception as exc:
            batch = getattr(inner, "batch", 1)
            if not _is_oom(exc) or batch <= 1:
                raise
            inner.batch = batch // 2
            _release_cuda_cache()
            if log is not None:
                print(f"out of memory at batch {batch}; retrying with {inner.batch}", file=log, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fill an embedding cache from request.json in a child process.")
    p.add_argument("--embedder", required=True, help="st:<hf-model> or hash:<dim>")
    p.add_argument("--work-dir", type=Path, required=True, help=f"holds {REQUEST_FILE} and the cache")
    p.add_argument("--query-instruction", default=None)
    p.add_argument("--device", default=None)
    p.add_argument("--max-seq-length", type=int, default=2048)
    p.add_argument("--batch", type=int, default=8)
    a = p.parse_args(argv)
    request = json.loads((a.work_dir / REQUEST_FILE).read_text(encoding="utf-8"))
    inner = make_inner(
        a.embedder,
        query_instruction=a.query_instruction,
        device=a.device,
        max_seq_length=a.max_seq_length,
        batch=a.batch,
    )
    cached = CachedEmbedder(inner, a.work_dir)
    embed_with_backoff(cached, inner, request["documents"], is_query=False, log=sys.stdout)
    embed_with_backoff(cached, inner, request["queries"], is_query=True, log=sys.stdout)
    print(
        f"embedded {len(request['documents'])} documents and {len(request['queries'])} queries "
        f"(final batch {getattr(inner, 'batch', '-')})",
        flush=True,
    )
    return 0


def embed_in_subprocess(
    spec: str,
    documents: Sequence[str],
    queries: Sequence[str],
    work_dir: Path,
    *,
    query_instruction: str | None = None,
    device: str | None = None,
    max_seq_length: int = 2048,
    batch: int = 8,
    log: Path | None = None,
    timeout_s: float = 3600,
) -> CachedEmbedder:
    """Embed ``documents`` and ``queries`` in a child process; return a cache-only embedder over the result.

    The returned embedder serves exactly these texts (documents as documents, queries as queries) and raises
    :class:`LookupError` for anything else.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    request = {"documents": list(documents), "queries": list(queries)}
    (work_dir / REQUEST_FILE).write_text(json.dumps(request), encoding="utf-8")
    cmd = [sys.executable, "-m", "onprem_genai.knowledge.embed_job", "--embedder", spec]
    cmd += ["--work-dir", str(work_dir), "--max-seq-length", str(max_seq_length), "--batch", str(batch)]
    if query_instruction:
        cmd += ["--query-instruction", query_instruction]
    if device:
        cmd += ["--device", device]
    env = {**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout_s, check=False)
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("$ " + " ".join(cmd) + "\n" + p.stdout + p.stderr, encoding="utf-8")
    if p.returncode != 0:
        tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-25:])
        raise RuntimeError(f"embedding process exited with code {p.returncode}:\n{tail}")
    return CachedEmbedder(CacheOnlyEmbedder(embedder_name(spec)), work_dir)


if __name__ == "__main__":
    raise SystemExit(main())
