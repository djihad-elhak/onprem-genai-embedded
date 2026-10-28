"""Async client for the engineering-knowledge MCP server (any transport the MCP SDK supports).

The agent reaches the knowledge graph only through MCP, exactly as an IDE assistant would: in production a
URL to
the shared ``knowledge-mcp`` service, in tests an in-process server instance.
"""

from __future__ import annotations

from typing import Any

from mcp import Client


class KnowledgeClient:
    def __init__(self, target: Any) -> None:  # URL string, MCPServer instance or MCP transport
        self._client = Client(target)
        self.calls: list[str] = []

    async def __aenter__(self) -> KnowledgeClient:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.__aexit__(*exc)  # type: ignore[arg-type]

    async def call(self, tool: str, **arguments: Any) -> Any:
        self.calls.append(tool)
        result = await self._client.call_tool(tool, arguments)
        if result.is_error:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            raise RuntimeError(f"MCP tool {tool} failed: {text[:300]}")
        data = result.structured_content
        if isinstance(data, dict) and set(data) == {"result"}:
            return data["result"]
        return data

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
