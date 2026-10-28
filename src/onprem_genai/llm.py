"""Minimal OpenAI-compatible chat client shared by the evaluation suite and the agent.

Works with any server exposing ``/v1/chat/completions`` (llama.cpp server, vLLM, SGLang, TGI, ...). No vendor
SDK: the platform runs air-gapped and the only contract is the HTTP API.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class Completion:
    text: str
    latency_s: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


class ChatModel:
    """Chat completions with bounded retries on transport errors and 5xx answers."""

    def __init__(
        self,
        base_url: str,
        model: str = "default",
        api_key: str | None = None,
        temperature: float = 0.2,
        top_p: float = 0.95,
        max_tokens: int = 4096,
        extra_body: dict[str, Any] | None = None,
        timeout_s: float = 900,
        retries: int = 2,
        backoff_s: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.model, self.retries, self.backoff_s = model, retries, backoff_s
        self.params = {
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            **(extra_body or {}),
        }
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(timeout=timeout_s, headers=headers, transport=transport)

    def complete(self, messages: list[dict[str, str]]) -> Completion:
        body = {"model": self.model, "messages": messages, **self.params}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            t0 = time.perf_counter()
            try:
                r = self.client.post(self.url, json=body)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"server error {r.status_code}", request=r.request, response=r
                    )
                r.raise_for_status()
                data = r.json()
                choice = data["choices"][0]
                usage = data.get("usage") or {}
                return Completion(
                    text=choice["message"].get("content") or "",
                    latency_s=time.perf_counter() - t0,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    finish_reason=choice.get("finish_reason"),
                )
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    break
                time.sleep(self.backoff_s * (attempt + 1))
        raise RuntimeError(f"chat completion failed: {last}") from last
