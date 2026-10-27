"""MCP server exposing the engineering knowledge graph to IDE assistants and agents.

Run over stdio (IDE integration) or streamable HTTP (shared platform service)::

    oge mcp serve --graph artifacts/fprime_graph.jsonl.gz                 # stdio
    oge mcp serve --graph ... --transport streamable-http --port 8765     # http://host:8765/mcp
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from onprem_genai.knowledge.store import KnowledgeStore

INSTRUCTIONS = (
    "Engineering knowledge graph of a flight-software code base: modules, source files, functions, unit "
    "tests, requirements (from design documents) and requirement->test traceability. Use `search` to find "
    "code, tests, requirements or design notes; `trace_requirement` to see which tests verify a requirement "
    "and which code implements it; `coverage_gaps` to list requirements without test evidence."
)

KINDS = "Function, TestCase, Requirement, DocChunk, Class"


def build_server(store: KnowledgeStore, name: str = "engineering-knowledge") -> MCPServer:
    server = MCPServer(name=name, instructions=INSTRUCTIONS, version="0.1.0")

    @server.tool(
        description="Hybrid (lexical + semantic + graph) search over code, tests, requirements and docs."
    )
    def search(
        query: Annotated[str, Field(description="Natural-language or code query")],
        k: Annotated[int, Field(ge=1, le=50, description="Number of results")] = 10,
        kinds: Annotated[list[str] | None, Field(description=f"Restrict to node kinds: {KINDS}")] = None,
        module: Annotated[
            str | None, Field(description="Restrict to a module, e.g. Svc/CmdDispatcher")
        ] = None,
    ) -> list[dict[str, Any]]:
        return [h.as_dict() for h in store.search(query, k=k, kinds=kinds, module=module)]

    @server.tool(description="Source code and location of a function, method, test or class by name.")
    def get_symbol(
        name: Annotated[str, Field(description="Short or qualified name, e.g. runNominalDispatch")],
        module: str | None = None,
    ) -> list[dict[str, Any]]:
        return store.find_symbol(name, module=module)

    @server.tool(
        description="Functions or tests that call the given function (by node id from search/get_symbol)."
    )
    def get_callers(node_id: str) -> list[dict[str, Any]]:
        return store.callers(node_id)

    @server.tool(description="Functions called by the given function or test (by node id).")
    def get_callees(node_id: str) -> list[dict[str, Any]]:
        return store.callees(node_id)

    @server.tool(
        description="Requirement text, verification method, owning module and explicitly tagged tests."
    )
    def get_requirement(
        req_id: Annotated[str, Field(description="Requirement ID, e.g. CD-001")],
    ) -> dict[str, Any]:
        return store.get_requirement(req_id) or {"error": f"unknown requirement {req_id}"}

    @server.tool(
        description="Traceability of one requirement: tagged tests, suggested tests and related code."
    )
    def trace_requirement(req_id: str, k: Annotated[int, Field(ge=1, le=20)] = 5) -> dict[str, Any]:
        return store.trace_requirement(req_id, k=k) or {"error": f"unknown requirement {req_id}"}

    @server.tool(
        description="Requirements verified by test (per their design document) that no test tags yet."
    )
    def coverage_gaps(module: str | None = None) -> list[dict[str, Any]]:
        return store.coverage_gaps(module)

    @server.tool(description="List modules with file, requirement and test counts.")
    def list_modules() -> list[dict[str, Any]]:
        return store.modules()

    @server.tool(description="Files, classes, requirements, design-doc sections and gap count of one module.")
    def module_overview(module: Annotated[str, Field(description="e.g. Svc/CmdSequencer")]) -> dict[str, Any]:
        return store.module_overview(module) or {"error": f"unknown module {module}"}

    return server
