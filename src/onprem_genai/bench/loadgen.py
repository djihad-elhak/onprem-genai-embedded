"""Closed-loop load generator for OpenAI-compatible inference servers (vLLM, llama.cpp, ...).

Each concurrency level runs ``concurrency`` workers that issue streaming chat requests back-to-back until
``n_requests`` have completed. Per request we record time-to-first-token (TTFT), inter-token latency (ITL)
and end-to-end latency; per level we report percentiles and aggregate throughput.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from onprem_genai.bench.profiles import Profile


@dataclass
class RequestResult:
    ok: bool
    ttft_s: float | None = None
    e2e_s: float | None = None
    itl_s: list[float] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None


@dataclass
class LevelSummary:
    profile: str
    concurrency: int
    n_requests: int
    n_errors: int
    wall_s: float
    output_tps: float
    requests_per_s: float
    ttft_p50_s: float | None
    ttft_p95_s: float | None
    tpot_p50_ms: float | None
    tpot_p95_ms: float | None
    e2e_p50_s: float | None
    e2e_p95_s: float | None
    mean_prompt_tokens: float | None
    mean_completion_tokens: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in [0, 100]); None for empty input."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


async def stream_chat(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    extra_body: dict[str, Any] | None = None,
    timeout_s: float = 900.0,
) -> RequestResult:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if extra_body:
        payload.update(extra_body)
    t0 = time.perf_counter()
    t_last: float | None = None
    res = RequestResult(ok=False)
    chunks = 0
    try:
        async with client.stream(
            "POST", f"{base_url}/v1/chat/completions", json=payload, timeout=timeout_s
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:300]
                res.error = f"HTTP {resp.status_code}: {body}"
                return res
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                obj = json.loads(data)
                usage = obj.get("usage")
                if usage:
                    res.prompt_tokens = usage.get("prompt_tokens")
                    res.completion_tokens = usage.get("completion_tokens")
                for choice in obj.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning"):
                        now = time.perf_counter()
                        if res.ttft_s is None:
                            res.ttft_s = now - t0
                        elif t_last is not None:
                            res.itl_s.append(now - t_last)
                        t_last = now
                        chunks += 1
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        res.error = f"{type(exc).__name__}: {exc}"
        return res
    res.e2e_s = time.perf_counter() - t0
    if res.completion_tokens is None:
        res.completion_tokens = chunks
    res.ok = res.ttft_s is not None
    if not res.ok:
        res.error = "no tokens received"
    return res


def summarize(profile: str, concurrency: int, results: list[RequestResult], wall_s: float) -> LevelSummary:
    ok = [r for r in results if r.ok]
    ttft = [r.ttft_s for r in ok if r.ttft_s is not None]
    e2e = [r.e2e_s for r in ok if r.e2e_s is not None]
    # Time per output token after the first one, per request (robust to servers that batch several tokens
    # per SSE chunk, unlike raw inter-chunk latency).
    tpot = [
        (r.e2e_s - r.ttft_s) / (r.completion_tokens - 1) * 1e3
        for r in ok
        if r.e2e_s is not None and r.ttft_s is not None and r.completion_tokens and r.completion_tokens > 1
    ]
    out_tokens = sum(r.completion_tokens or 0 for r in ok)
    prompts = [r.prompt_tokens for r in ok if r.prompt_tokens is not None]
    completions = [r.completion_tokens for r in ok if r.completion_tokens is not None]
    return LevelSummary(
        profile=profile,
        concurrency=concurrency,
        n_requests=len(results),
        n_errors=len(results) - len(ok),
        wall_s=round(wall_s, 3),
        output_tps=round(out_tokens / wall_s, 2) if wall_s > 0 else 0.0,
        requests_per_s=round(len(ok) / wall_s, 3) if wall_s > 0 else 0.0,
        ttft_p50_s=percentile(ttft, 50),
        ttft_p95_s=percentile(ttft, 95),
        tpot_p50_ms=percentile(tpot, 50),
        tpot_p95_ms=percentile(tpot, 95),
        e2e_p50_s=percentile(e2e, 50),
        e2e_p95_s=percentile(e2e, 95),
        mean_prompt_tokens=statistics.fmean(prompts) if prompts else None,
        mean_completion_tokens=statistics.fmean(completions) if completions else None,
    )


async def run_level(
    base_url: str,
    model: str,
    profile: Profile,
    concurrency: int,
    n_requests: int,
    extra_body: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[LevelSummary, list[RequestResult]]:
    owns_client = client is None
    client = client or httpx.AsyncClient(limits=httpx.Limits(max_connections=concurrency * 2))
    queue: asyncio.Queue[int] = asyncio.Queue()
    for i in range(n_requests):
        queue.put_nowait(i)
    results: list[RequestResult] = []

    async def worker() -> None:
        while True:
            try:
                i = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            messages, max_tokens = profile.request(i)
            results.append(await stream_chat(client, base_url, model, messages, max_tokens, extra_body))

    t0 = time.perf_counter()
    try:
        await asyncio.gather(*(worker() for _ in range(concurrency)))
    finally:
        if owns_client:
            await client.aclose()
    wall = time.perf_counter() - t0
    return summarize(profile.name, concurrency, results, wall), results


async def sweep(
    base_url: str,
    model: str,
    profile: Profile,
    concurrencies: Sequence[int],
    requests_per_level: int,
    extra_body: dict[str, Any] | None = None,
    warmup_requests: int = 2,
) -> list[LevelSummary]:
    """Run a warm-up, then each concurrency level in order."""
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=max(concurrencies) * 2)) as client:
        if warmup_requests:
            await run_level(base_url, model, profile, 1, warmup_requests, extra_body, client)
        out = []
        for c in concurrencies:
            summary, _ = await run_level(
                base_url, model, profile, c, max(requests_per_level, c), extra_body, client
            )
            out.append(summary)
        return out
