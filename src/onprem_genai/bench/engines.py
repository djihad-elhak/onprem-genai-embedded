"""Inference-engine lifecycle for benchmarks: build/install, launch, health-check, GPU sampling, teardown.

Used by the Kaggle notebooks; everything is plain subprocess + HTTP so it also works on a bare Linux GPU host.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx


# ------------------------------------------------------------------------------------------- GPU telemetry
def gpu_memory_mib() -> list[int]:
    """Used memory per GPU (MiB); empty list when no NVIDIA GPU is visible."""
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    try:
        return [int(x.strip()) for x in p.stdout.strip().splitlines() if x.strip()]
    except ValueError:
        return []


class GpuPeakSampler:
    """Background sampler keeping per-GPU peak memory while a measurement runs."""

    def __init__(self, interval_s: float = 0.5) -> None:
        self.interval_s = interval_s
        self.peak_mib: list[int] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            cur = gpu_memory_mib()
            if cur:
                self.peak_mib = (
                    cur
                    if not self.peak_mib
                    else [max(a, b) for a, b in zip(self.peak_mib, cur, strict=False)]
                )
            self._stop.wait(self.interval_s)

    def __enter__(self) -> GpuPeakSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def wait_gpu_released(threshold_mib: int = 600, timeout_s: float = 120) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        mem = gpu_memory_mib()
        if not mem or max(mem) < threshold_mib:
            return
        time.sleep(2)


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) != 0


def tail(path: Path, n: int = 60) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


# ------------------------------------------------------------------------------------------- server process
@dataclass
class ServerProcess:
    """An OpenAI-compatible server started as its own process group (so TP workers die with it)."""

    cmd: Sequence[str]
    log_path: Path
    port: int
    env: dict[str, str] = field(default_factory=dict)
    host: str = "127.0.0.1"
    proc: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if not port_free(self.port, self.host):
            raise RuntimeError(f"port {self.port} already in use")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("wb") as log:
            log.write(("$ " + " ".join(self.cmd) + "\n").encode())
        log_handle = self.log_path.open("ab")  # kept open for the child's lifetime, closed in stop()
        self._log_handle = log_handle
        self.proc = subprocess.Popen(
            list(self.cmd),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env={**os.environ, **self.env},
            start_new_session=True,
        )

    def wait_ready(self, timeout_s: float) -> tuple[bool, str]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.proc is None or self.proc.poll() is not None:
                code = None if self.proc is None else self.proc.returncode
                return False, f"process exited with code {code}"
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(f"{self.base_url}/health", timeout=5).status_code == 200:
                    return True, "ok"
            time.sleep(2)
        return False, f"not ready after {timeout_s:.0f}s"

    def stop(self, release_gpu: bool = True) -> None:
        if self.proc is not None and self.proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=45)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=15)
        handle = getattr(self, "_log_handle", None)
        if handle is not None:
            handle.close()
        if release_gpu:
            wait_gpu_released()

    def __enter__(self) -> ServerProcess:
        self.start()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.stop()


# ------------------------------------------------------------------------------------------- commands
def llamacpp_command(
    server_bin: Path, model_path: Path, *, port: int, ctx_total: int, parallel: int, extra: Sequence[str] = ()
) -> list[str]:
    return [
        str(server_bin),
        "-m",
        str(model_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "-ngl",
        "999",
        "-c",
        str(ctx_total),
        "--parallel",
        str(parallel),
        "--jinja",
        "--metrics",
        *extra,
    ]


def binary_supports(binary: Path, flag: str, subcommand: Sequence[str] = ()) -> bool:
    """Whether ``binary [subcommand] --help`` mentions ``flag`` (engines add and rename flags often)."""
    try:
        p = subprocess.run(
            [str(binary), *subcommand, "--help"], capture_output=True, text=True, timeout=300, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return flag in (p.stdout + p.stderr)


def vllm_command(
    vllm_bin: Path,
    model: str,
    *,
    port: int,
    tensor_parallel: int,
    max_model_len: int,
    gpu_memory_utilization: float = 0.9,
    dtype: str = "half",
    extra: Sequence[str] = (),
) -> list[str]:
    return [
        str(vllm_bin),
        "serve",
        model,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--served-model-name",
        "default",
        "--tensor-parallel-size",
        str(tensor_parallel),
        "--dtype",
        dtype,
        "--max-model-len",
        str(max_model_len),
        "--gpu-memory-utilization",
        str(gpu_memory_utilization),
        "--trust-remote-code",
        *extra,
    ]


def build_llamacpp(
    work_dir: Path, cuda_arch: str = "75", ref: str | None = None, log: Path | None = None
) -> Path:
    """Clone and build ``llama-server`` with CUDA for one architecture; returns the binary path."""
    src = work_dir / "llama.cpp"
    server = src / "build" / "bin" / "llama-server"
    if server.exists():
        return server
    branch = ["--branch", ref] if ref else []
    subprocess.run(
        ["git", "clone", "--depth", "1", *branch, "https://github.com/ggml-org/llama.cpp", str(src)],
        check=True,
    )
    env = {**os.environ, "PATH": f"/usr/local/cuda/bin:{os.environ.get('PATH', '')}"}
    out = subprocess.run(
        f"cmake -S . -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES={cuda_arch} -DLLAMA_CURL=OFF "
        f"-DCMAKE_BUILD_TYPE=Release && cmake --build build --config Release -j{os.cpu_count() or 4} "
        "--target llama-server",
        shell=True,
        cwd=src,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if log is not None:
        log.write_text(out.stdout + out.stderr)
    if out.returncode != 0:
        raise RuntimeError(f"llama.cpp build failed:\n{(out.stdout + out.stderr)[-3000:]}")
    return server


def install_vllm(work_dir: Path, spec: str = "vllm", python: str = "3.12", log: Path | None = None) -> Path:
    """Install vLLM in an isolated uv venv (host PyTorch untouched); returns the ``vllm`` CLI path."""
    venv = work_dir / "vllm-venv"
    cli = venv / "bin" / "vllm"
    if cli.exists():
        return cli
    uv = shutil.which("uv") or "uv"
    steps = [
        [uv, "venv", str(venv), "--python", python, "--seed"],
        [uv, "pip", "install", "--python", str(venv / "bin" / "python"), spec],
    ]
    text = ""
    for cmd in steps:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        text += p.stdout + p.stderr
        if p.returncode != 0:
            if log is not None:
                log.write_text(text)
            raise RuntimeError(f"vLLM install failed: {' '.join(cmd)}\n{text[-3000:]}")
    if log is not None:
        log.write_text(text)
    return cli


# ------------------------------------------------------------------------------------------- model files
def resolve_gguf_files(files: Sequence[str], quant: str) -> list[str]:
    """GGUF file(s) for a quantization in a repo listing: all shards if split, non-UD preferred."""
    pat = re.compile(rf"(^|[-_./]){re.escape(quant)}([-_.]|$)", re.IGNORECASE)
    ggufs = [f for f in files if f.endswith(".gguf") and "mmproj" not in f.lower() and pat.search(f)]
    if not ggufs:
        raise FileNotFoundError(
            f"no {quant} GGUF; available: {sorted(f for f in files if f.endswith('.gguf'))[:20]}"
        )
    plain = sorted([f for f in ggufs if "UD-" not in f] or ggufs)
    m = re.match(r"(.*)-\d{5}-of-\d{5}\.gguf$", plain[0])
    if m:
        return sorted(
            f for f in plain if f.startswith(m.group(1)) and re.search(r"-\d{5}-of-\d{5}\.gguf$", f)
        )
    return [plain[0]]


def download_gguf(repo: str, quant: str, dest: Path) -> Path:
    from huggingface_hub import HfApi, hf_hub_download  # noqa: PLC0415  (optional, notebook-only)

    files = resolve_gguf_files(HfApi().list_repo_files(repo), quant)
    paths = [Path(hf_hub_download(repo, f, local_dir=dest)) for f in files]
    return sorted(paths)[0]


def gguf_metadata(path: Path) -> dict[str, Any]:
    """Scalar architecture metadata from a GGUF header (layers, heads, context, experts, SSM...)."""
    from gguf import GGUFReader  # noqa: PLC0415  (optional dependency: extra 'bench')

    reader = GGUFReader(str(path))
    out: dict[str, Any] = {}
    for name, fld in reader.fields.items():
        if name.startswith("tokenizer.") or not fld.types:
            continue
        try:
            value = fld.contents()
        except Exception:
            continue
        if isinstance(value, str | int | float | bool) or (
            isinstance(value, list) and len(value) <= 512 and all(isinstance(v, int | float) for v in value)
        ):
            out[name] = value
    out["file_bytes"] = path.stat().st_size if path.exists() else None
    return out


def parse_vllm_log(text: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    if m := re.search(r"GPU KV cache size:\s*([\d,]+)\s*tokens", text):
        info["kv_cache_tokens"] = int(m.group(1).replace(",", ""))
    if m := re.search(r"Maximum concurrency for\s*([\d,]+)\s*tokens per request:\s*([\d.]+)x", text):
        info["max_concurrency_at_len"] = {"tokens": int(m.group(1).replace(",", "")), "x": float(m.group(2))}
    if m := re.search(r"Model loading took\s*([\d.]+)\s*Gi?B", text):
        info["weights_gib_per_rank"] = float(m.group(1))
    backends = sorted(set(re.findall(r"Using\s+([A-Za-z0-9_.]+)\s+(?:attention\s+)?backend", text)))
    if backends:
        info["backends"] = backends
    return info
