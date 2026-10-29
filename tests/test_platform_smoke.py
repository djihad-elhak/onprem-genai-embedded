"""Integration test: the MCP server over real streamable HTTP + mock LLM/embedding endpoints + smoke test."""

from __future__ import annotations

import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from onprem_genai.knowledge.model import Graph
from onprem_genai.platform.smoke import check_egress, run_smoke

MOCK_OPENAI = textwrap.dedent(
    """
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            healthy = self.path == "/health"
            self._send({"status": "ok"} if healthy else {}, 200 if healthy else 404)

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if self.headers.get("Authorization") != "Bearer secret":
                return self._send({"error": "unauthorized"}, 401)
            if self.path.endswith("/chat/completions"):
                reply = {"choices": [{"message": {"content": "READY"}}], "usage": {"total_tokens": 3}}
                return self._send(reply)
            if self.path.endswith("/embeddings"):
                return self._send({"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})
            self._send({}, 404)

    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
    """
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, timeout_s: float = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise TimeoutError(f"port {port} not listening")


@pytest.fixture
def services(tmp_path: Path, mini_graph: Graph):
    snapshot = tmp_path / "graph.jsonl.gz"
    mini_graph.save(snapshot)
    llm_port, mcp_port = _free_port(), _free_port()
    (tmp_path / "mock.py").write_text(MOCK_OPENAI)
    procs = [
        subprocess.Popen([sys.executable, str(tmp_path / "mock.py"), str(llm_port)]),
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "onprem_genai.cli",
                "mcp",
                "serve",
                "--graph",
                str(snapshot),
                "--transport",
                "streamable-http",
                "--port",
                str(mcp_port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=(tmp_path / "mcp.log").open("w"),
        ),
    ]
    try:
        _wait_port(llm_port)
        _wait_port(mcp_port)
        yield f"http://127.0.0.1:{llm_port}", f"http://127.0.0.1:{mcp_port}/mcp"
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=10)


def test_smoke_against_live_http_services(services: tuple[str, str]) -> None:
    llm, mcp = services
    report = run_smoke(llm_url=llm, embed_url=llm, mcp_url=mcp, expect_offline=False, api_key="secret")
    checks = {c["name"]: c for c in report["checks"]}
    assert report["passed"], report
    assert checks["llm_chat"]["detail"]["reply"] == "READY"
    assert checks["embeddings"]["detail"]["dimensions"] == 3
    mcp_detail = checks["knowledge_mcp"]["detail"]
    assert {"search", "trace_requirement", "coverage_gaps"} <= set(mcp_detail["tools"])
    assert mcp_detail["coverage_gaps"] == 1  # FOO-004 (BAR-001 is tagged, albeit from another module)


def test_smoke_rejects_missing_api_key(services: tuple[str, str]) -> None:
    llm, _ = services
    report = run_smoke(llm_url=llm, embed_url=None, mcp_url=None, expect_offline=False, api_key=None)
    assert not report["passed"]
    assert "401" in report["checks"][0]["detail"]["error"]


def test_egress_check_semantics() -> None:
    assert check_egress(expect_blocked=False, timeout_s=0.5)["ok"] is True
    blocked = check_egress(expect_blocked=True, timeout_s=0.5)
    assert blocked["ok"] == (not blocked["reachable"])


def test_chat_check_accepts_a_reasoning_only_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx  # noqa: PLC0415

    from onprem_genai.platform import smoke  # noqa: PLC0415

    sent: dict = {}

    def fake_post(url: str, **kw: object) -> httpx.Response:
        sent.update(kw["json"])  # type: ignore[arg-type]
        body = {"choices": [{"message": {"content": "", "reasoning_content": "The user wants READY."}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(smoke.httpx, "post", fake_post)
    res = smoke.check_chat("http://llm:8080")
    assert res["ok"] is True
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
