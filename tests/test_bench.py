from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from onprem_genai.bench.loadgen import RequestResult, percentile, run_level, summarize
from onprem_genai.bench.profiles import make_profiles, synthetic_corpus


def _sse_server(fail_every: int = 0) -> httpx.MockTransport:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if fail_every and calls["n"] % fail_every == 0:
            return httpx.Response(500, content=b"boom")
        body = json.loads(request.content)
        n_tokens = min(body["max_tokens"], 20)

        async def stream():
            for i in range(n_tokens):
                await asyncio.sleep(0.001)
                chunk = {"choices": [{"index": 0, "delta": {"content": f"t{i} "}}]}
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            usage = {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": n_tokens}}
            yield f"data: {json.dumps(usage)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return httpx.Response(200, content=stream(), headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


def test_percentile() -> None:
    assert percentile([], 50) is None
    assert percentile([3.0], 95) == 3.0
    assert percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    assert percentile(list(range(101)), 95) == pytest.approx(95)


def test_profiles_are_deterministic_and_agent_shares_prefix() -> None:
    profiles = make_profiles(synthetic_corpus(), scale=0.2)
    chat = profiles["chat"]
    assert chat.request(3) == chat.request(3)
    assert chat.request(3) != chat.request(4)
    agent = profiles["agent"]
    sys_a, sys_b = agent.request(1)[0][0]["content"], agent.request(2)[0][0]["content"]
    assert sys_a == sys_b  # shared repository prefix -> prefix-cache friendly
    assert agent.request(1)[0][1] != agent.request(2)[0][1]


def test_run_level_collects_metrics() -> None:
    prof = make_profiles(synthetic_corpus(), scale=0.1)["chat"]

    async def go():
        async with httpx.AsyncClient(transport=_sse_server()) as client:
            return await run_level("http://mock", "m", prof, concurrency=4, n_requests=10, client=client)

    summary, results = asyncio.run(go())
    assert summary.n_requests == 10
    assert summary.n_errors == 0
    assert all(r.completion_tokens == 20 and r.prompt_tokens == 100 for r in results)
    assert summary.ttft_p50_s is not None
    assert summary.tpot_p50_ms is not None
    assert summary.output_tps > 0


def test_run_level_counts_http_errors() -> None:
    prof = make_profiles(synthetic_corpus(), scale=0.1)["completion"]

    async def go():
        async with httpx.AsyncClient(transport=_sse_server(fail_every=3)) as client:
            return await run_level("http://mock", "m", prof, concurrency=2, n_requests=9, client=client)

    summary, results = asyncio.run(go())
    assert summary.n_errors == 3
    assert all("HTTP 500" in (r.error or "") for r in results if not r.ok)


def test_summarize_tpot() -> None:
    rs = [RequestResult(ok=True, ttft_s=0.5, e2e_s=1.5, completion_tokens=11)]
    s = summarize("x", 1, rs, wall_s=1.5)
    assert s.tpot_p50_ms == pytest.approx(100.0)
    assert s.output_tps == pytest.approx(11 / 1.5, rel=1e-3)


def test_run_blocking_inside_running_loop() -> None:
    from onprem_genai.bench.loadgen import run_blocking  # noqa: PLC0415

    async def value() -> int:
        await asyncio.sleep(0)
        return 7

    async def outer() -> int:
        return run_blocking(value())  # would fail with plain asyncio.run inside a loop

    assert run_blocking(value()) == 7
    assert asyncio.run(outer()) == 7
