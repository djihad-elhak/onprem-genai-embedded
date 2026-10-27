"""End-to-end platform smoke test: LLM, embeddings, knowledge MCP server and network isolation.

Run inside the deployment network (``deploy/docker-compose.offline.yml``) to prove the platform works
with no outbound connectivity, or against any host for a quick health check. Exit code 0 only if every
check passes.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

EGRESS_PROBES = (("1.1.1.1", 443), ("8.8.8.8", 53), ("huggingface.co", 443), ("pypi.org", 443))


@dataclass
class Check:
    name: str
    ok: bool
    seconds: float
    detail: dict[str, Any] = field(default_factory=dict)


def _timed(name: str, fn: Callable[[], dict[str, Any]]) -> Check:
    t = time.perf_counter()
    try:
        detail = fn()
        ok = bool(detail.pop("ok", True))
    except Exception as exc:
        detail, ok = {"error": f"{type(exc).__name__}: {exc}"}, False
    return Check(name, ok, round(time.perf_counter() - t, 3), detail)


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def check_chat(base_url: str, api_key: str | None = None, model: str = "default") -> dict[str, Any]:
    r = httpx.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        headers=_headers(api_key),
        json={
            "model": model,
            "max_tokens": 32,
            "temperature": 0,
            "messages": [{"role": "user", "content": "Reply with the word READY."}],
        },
        timeout=300,
    )
    r.raise_for_status()
    text = r.json()["choices"][0]["message"].get("content") or ""
    return {"ok": bool(text.strip()), "reply": text[:80], "usage": r.json().get("usage")}


def check_embeddings(base_url: str, api_key: str | None = None, model: str = "default") -> dict[str, Any]:
    r = httpx.post(
        f"{base_url.rstrip('/')}/v1/embeddings",
        headers=_headers(api_key),
        json={"model": model, "input": ["command dispatcher queue overflow"]},
        timeout=120,
    )
    r.raise_for_status()
    vec = r.json()["data"][0]["embedding"]
    return {"ok": len(vec) > 0, "dimensions": len(vec)}


async def _mcp(url: str) -> dict[str, Any]:
    from mcp import Client  # noqa: PLC0415

    async with Client(url) as client:
        tools = sorted(t.name for t in (await client.list_tools()).tools)
        search = await client.call_tool("search", {"query": "drop commands when the queue is full", "k": 3})
        gaps = await client.call_tool("coverage_gaps", {})
    hits = (search.structured_content or {}).get("result", [])
    n_gaps = len((gaps.structured_content or {}).get("result", []))
    return {
        "ok": bool(hits) and not search.is_error,
        "tools": tools,
        "top_hit": hits[0]["title"] if hits else None,
        "coverage_gaps": n_gaps,
    }


def check_mcp(url: str) -> dict[str, Any]:
    return asyncio.run(_mcp(url))


def check_egress(expect_blocked: bool, timeout_s: float = 3.0) -> dict[str, Any]:
    """Try outbound TCP connections; in offline mode every attempt must fail."""
    reachable = []
    for host, port in EGRESS_PROBES:
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                reachable.append(f"{host}:{port}")
        except OSError:
            continue
    ok = not reachable if expect_blocked else True
    return {"ok": ok, "expect_blocked": expect_blocked, "reachable": reachable}


def run_smoke(
    *,
    llm_url: str | None,
    embed_url: str | None,
    mcp_url: str | None,
    expect_offline: bool,
    api_key: str | None = None,
    wait_s: float = 0.0,
) -> dict[str, Any]:
    if wait_s:
        _wait_for([u for u in (llm_url, embed_url) if u], wait_s)
    checks: list[Check] = []
    if llm_url:
        checks.append(_timed("llm_chat", lambda: check_chat(llm_url, api_key)))
    if embed_url:
        checks.append(_timed("embeddings", lambda: check_embeddings(embed_url, api_key)))
    if mcp_url:
        checks.append(_timed("knowledge_mcp", lambda: check_mcp(mcp_url)))
    checks.append(_timed("egress", lambda: check_egress(expect_offline)))
    return {"passed": all(c.ok for c in checks), "checks": [asdict(c) for c in checks]}


def _wait_for(urls: list[str], timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    pending = set(urls)
    while pending and time.time() < deadline:
        for u in list(pending):
            try:
                if httpx.get(f"{u.rstrip('/')}/health", timeout=5).status_code == 200:
                    pending.discard(u)
            except httpx.HTTPError:
                pass
        if pending:
            time.sleep(3)


def main_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2)
