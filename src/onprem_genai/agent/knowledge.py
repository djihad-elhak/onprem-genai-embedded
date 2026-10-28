"""Async MCP tool clients used by the agent: the engineering-knowledge server and any other MCP server.

The agent reaches the knowledge graph and the CI only through MCP, exactly as an IDE assistant would:
in production a URL to the shared service, in tests an in-process server instance.
"""

from __future__ import annotations

import json
from typing import Any

from mcp import Client

_ENVELOPE = {"status", "message", "result"}


def mcp_target(target: Any, headers: dict[str, str] | None = None, timeout_s: float = 300) -> Any:
    """A URL with HTTP headers (e.g. ``Authorization``) becomes a streamable-HTTP transport; others pass."""
    if not headers or not isinstance(target, str):
        return target
    import httpx2  # noqa: PLC0415  (the HTTP client the MCP SDK is built on)
    from mcp.client.streamable_http import streamable_http_client  # noqa: PLC0415

    client = httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(timeout_s, connect=30))
    return streamable_http_client(target, http_client=client)


def decode_result(structured: Any, texts: list[str]) -> Any:
    """Tool payload from either structured content or JSON text content.

    Handles the MCP SDK convention (lists wrapped as ``{"result": [...]}``) and the envelope of the Jenkins
    MCP plugin (``{"status": "COMPLETED", "message": ..., "result": ...}``; no ``result`` means no data).
    """
    data: Any = structured
    if data is None and texts:
        joined = "".join(texts)
        try:
            data = json.loads(joined)
        except json.JSONDecodeError:
            return joined
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return data
    if isinstance(data, dict) and {"status", "message"} <= set(data) <= _ENVELOPE:
        return data.get("result")
    return data


class McpToolClient:
    """Calls tools of one MCP server; ``target`` is a URL, an ``MCPServer`` instance or an MCP transport."""

    def __init__(self, target: Any, headers: dict[str, str] | None = None) -> None:
        self._client = Client(mcp_target(target, headers))
        self.calls: list[str] = []

    async def __aenter__(self) -> McpToolClient:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.__aexit__(*exc)  # type: ignore[arg-type]

    async def tool_names(self) -> list[str]:
        return [t.name for t in (await self._client.list_tools()).tools]

    async def call(self, tool: str, **arguments: Any) -> Any:
        self.calls.append(tool)
        args = {k: v for k, v in arguments.items() if v is not None}
        result = await self._client.call_tool(tool, args)
        texts = [str(c.text) for c in result.content if getattr(c, "text", None) is not None]  # type: ignore[union-attr]
        if result.is_error:
            raise RuntimeError(f"MCP tool {tool} failed: {' '.join(texts)[:300]}")
        return decode_result(result.structured_content, texts)


class KnowledgeClient(McpToolClient):
    """Typed helpers over the engineering-knowledge MCP server (``onprem_genai.mcp_server``)."""

    async def __aenter__(self) -> KnowledgeClient:
        await super().__aenter__()
        return self

    async def requirement(self, req_id: str) -> dict[str, Any]:
        return await self.call("get_requirement", req_id=req_id)

    async def trace(self, req_id: str, k: int = 5) -> dict[str, Any]:
        return await self.call("trace_requirement", req_id=req_id, k=k)

    async def search(
        self, query: str, k: int = 5, kinds: list[str] | None = None, module: str | None = None
    ) -> list[dict[str, Any]]:
        return await self.call("search", query=query, k=k, kinds=kinds, module=module)

    async def symbol(self, name: str, module: str | None = None) -> list[dict[str, Any]]:
        return await self.call("get_symbol", name=name, module=module)

    async def gaps(self, module: str | None = None) -> list[dict[str, Any]]:
        return await self.call("coverage_gaps", module=module)
