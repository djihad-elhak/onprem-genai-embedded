from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from onprem_genai.bench.engines import (
    ServerProcess,
    llamacpp_command,
    parse_vllm_log,
    port_free,
    resolve_gguf_files,
    vllm_command,
)

MOCK_SERVER = textwrap.dedent(
    """
    import sys
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404)
            self.end_headers()

    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
    """
)


def _free_port() -> int:
    import socket  # noqa: PLC0415

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (["m-Q4_K_M.gguf", "m-UD-Q4_K_XL.gguf", "mmproj-F16.gguf", "m-Q8_0.gguf"], ["m-Q4_K_M.gguf"]),
        (["m-UD-Q4_K_M.gguf", "m-Q4_K_M.gguf"], ["m-Q4_K_M.gguf"]),
        (
            ["Q4_K_M/m-Q4_K_M-00002-of-00002.gguf", "Q4_K_M/m-Q4_K_M-00001-of-00002.gguf", "Q8_0/x.gguf"],
            ["Q4_K_M/m-Q4_K_M-00001-of-00002.gguf", "Q4_K_M/m-Q4_K_M-00002-of-00002.gguf"],
        ),
    ],
)
def test_resolve_gguf_files(files: list[str], expected: list[str]) -> None:
    assert resolve_gguf_files(files, "Q4_K_M") == expected


def test_resolve_gguf_missing() -> None:
    with pytest.raises(FileNotFoundError):
        resolve_gguf_files(["m-Q8_0.gguf"], "Q4_K_M")


def test_commands() -> None:
    cmd = llamacpp_command(Path("/b/llama-server"), Path("/m.gguf"), port=9000, ctx_total=8192, parallel=4)
    assert cmd[:3] == ["/b/llama-server", "-m", "/m.gguf"]
    assert "--parallel" in cmd
    v = vllm_command(
        Path("/v/vllm"),
        "org/model",
        port=9000,
        tensor_parallel=2,
        max_model_len=16384,
        extra=["--enforce-eager"],
    )
    assert v[1:3] == ["serve", "org/model"]
    assert v[v.index("--tensor-parallel-size") + 1] == "2"
    assert v[-1] == "--enforce-eager"


def test_parse_vllm_log() -> None:
    info = parse_vllm_log(
        "Using AttentionBackendEnum.TRITON_ATTN backend.\nModel loading took 8.5 GiB\n"
        "GPU KV cache size: 98,304 tokens\nMaximum concurrency for 16,384 tokens per request: 6.00x\n"
    )
    assert info == {
        "backends": ["AttentionBackendEnum.TRITON_ATTN"],
        "kv_cache_tokens": 98304,
        "max_concurrency_at_len": {"tokens": 16384, "x": 6.0},
        "weights_gib_per_rank": 8.5,
    }


def test_server_process_lifecycle(tmp_path: Path) -> None:
    script = tmp_path / "srv.py"
    script.write_text(MOCK_SERVER)
    port = _free_port()
    srv = ServerProcess([sys.executable, str(script), str(port)], tmp_path / "log.txt", port)
    with srv:
        ok, why = srv.wait_ready(timeout_s=20)
        assert ok, why
        assert not port_free(port)
    assert port_free(port)
    assert (tmp_path / "log.txt").read_text().startswith("$ ")


def test_server_process_reports_crash(tmp_path: Path) -> None:
    srv = ServerProcess([sys.executable, "-c", "import sys; sys.exit(3)"], tmp_path / "log.txt", _free_port())
    srv.start()
    ok, why = srv.wait_ready(timeout_s=10)
    srv.stop(release_gpu=False)
    assert not ok
    assert "code 3" in why
