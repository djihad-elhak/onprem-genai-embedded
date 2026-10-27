# %% [markdown]
# # 00 · Hardware & model compatibility probe (Kaggle 2× Tesla T4)
#
# **Purpose.** Before committing to any model or inference engine, measure what *actually* runs on the
# available hardware: 2× NVIDIA Tesla T4 (Turing, SM 7.5, 15 GiB each, FP16 only — no BF16, no FP8,
# no FlashAttention-2). Every later design decision (model shortlist, engine choice, sizing calculator
# calibration) is based on these measurements, not on assumptions.
#
# **What it does** — for each candidate open-weight code model, on two engines:
#
# | Engine | Why |
# |---|---|
# | `llama.cpp` (`llama-server`, built from source for SM 7.5) | GGUF quantization, widest hardware support, typical single-team on-prem server |
# | `vLLM` (isolated venv) | Production-grade serving engine (continuous batching, paged KV cache, tensor parallelism) |
#
# it records: load success / failure reason, load time, VRAM per GPU, single-stream TTFT and decode speed,
# prefill speed on a ~6k-token prompt, aggregate throughput with 4 concurrent requests, max context that fits,
# and a functional smoke test (the model writes a C99 CRC-16 function that is compiled with `gcc -Wall -Wextra`
# and checked against known test vectors).
#
# **How to run (≈ 2–3 h of GPU quota):**
# 1. Kaggle → *Create* → *Import Notebook* → upload this `.ipynb`.
# 2. Right panel → *Session options*: **Accelerator = GPU T4 ×2**, **Internet = On**.
# 3. *Save Version* → **Save & Run All (Commit)**. It runs in the background; you can close the tab.
# 4. When finished, open the version → *Output* → download the `probe/` folder
#    (`probe_results.json`, `probe_report.md`, `logs/`).
#
# Results are written incrementally after every measurement, so a crash or timeout never loses completed work.
# Optional: add a Kaggle secret named `HF_TOKEN` to avoid Hugging Face rate limits (not required).

# %%
# ---------------------------------------------------------------- configuration
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

PROBE_VERSION = "0.1.0"
SESSION_BUDGET_S = 10.5 * 3600  # Kaggle sessions stop at 12 h; keep a safety margin
T_START = time.time()

RUN_LLAMACPP = os.environ.get("PROBE_RUN_LLAMACPP", "1") == "1"
RUN_VLLM = os.environ.get("PROBE_RUN_VLLM", "1") == "1"

LLAMACPP_GIT = "https://github.com/ggml-org/llama.cpp"
LLAMACPP_REF = None  # None = latest default branch; the exact commit is recorded in the results
VLLM_PIP_SPEC = "vllm"  # resolved version is recorded in the results

# Candidate models. GGUF files are resolved from the repo listing at run time (no hard-coded file names).
# vLLM on Turing needs 4-bit AWQ/GPTQ checkpoints (FP8/BF16 are not supported on SM 7.5);
# repos are tried in order and the one that worked is recorded.
CANDIDATES = [
    {
        "key": "qwen3.8-27b",
        "family": "Qwen (Alibaba)",
        "arch": "dense 27B, hybrid linear/full attention (48 linear + 16 full layers)",
        "license": "Apache-2.0",
        "gguf_repo": "unsloth/Qwen3.8-27B-GGUF",
        "gguf_quant": "Q4_K_M",
        "vllm_repos": ["mattbucci/Qwen3.8-27B-AWQ", "bernhardbrieger/Qwen3.8-27B-GPTQ-Int4"],
        "vllm_extra_if_supported": [["--gdn-prefill-backend", "triton"]],
        "vllm_extra": [],
        "disable_thinking": True,
    },
    {
        "key": "qwen3-coder-30b-a3b",
        "family": "Qwen (Alibaba)",
        "arch": "MoE 30B total / 3.3B active, full attention",
        "license": "Apache-2.0",
        "gguf_repo": "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF",
        "gguf_quant": "Q4_K_M",
        "vllm_repos": ["QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ"],
        "vllm_extra_if_supported": [],
        "vllm_extra": ["--enable-expert-parallel"],
        "disable_thinking": False,
    },
    {
        "key": "devstral-small-2-24b",
        "family": "Devstral (Mistral AI)",
        "arch": "dense 24B, full attention",
        "license": "Apache-2.0",
        "gguf_repo": "unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF",
        "gguf_quant": "Q4_K_M",
        "vllm_repos": [],
        "vllm_extra_if_supported": [],
        "vllm_extra": [],
        "disable_thinking": False,
    },
    {
        "key": "qwen3.6-35b-a3b",
        "family": "Qwen (Alibaba)",
        "arch": "MoE 35B total / 3B active, hybrid linear/full attention",
        "license": "Apache-2.0",
        "gguf_repo": "unsloth/Qwen3.6-35B-A3B-GGUF",
        "gguf_quant": "Q4_K_M",
        "vllm_repos": [],
        "vllm_extra_if_supported": [],
        "vllm_extra": [],
        "disable_thinking": True,
    },
]

# llama.cpp server launches per model: (label, n_parallel_slots, total_ctx)
LLAMACPP_LAUNCHES = [
    ("single_16k", 1, 16384),
    ("concurrent_4x8k", 4, 32768),
    ("single_64k", 1, 65536),
]
VLLM_MAX_MODEL_LEN = 16384
VLLM_GPU_MEM_UTIL = 0.90
CONCURRENCY = 4
SERVER_PORT = 8080

# ---------------------------------------------------------------- paths
OUT_DIR = Path("/kaggle/working/probe") if Path("/kaggle/working").exists() else Path.cwd() / "probe"
LOG_DIR = OUT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = OUT_DIR / "probe_results.json"
REPORT_PATH = OUT_DIR / "probe_report.md"


def _free_gb(p: str) -> float:
    try:
        return shutil.disk_usage(p).free / 1e9
    except OSError:
        return -1.0


# Large files (models, venv, build) go to the scratch location with the most free space,
# never to /kaggle/working (20 GB output limit).
_scratch_candidates = [p for p in ["/kaggle/temp", "/tmp"] if Path(p).exists()]
WORK_DIR = Path(max(_scratch_candidates, key=_free_gb)) / "probe_work"
WORK_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR = WORK_DIR / "models"
HF_HOME = WORK_DIR / "hf"
os.environ["HF_HOME"] = str(HF_HOME)
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
print(f"OUT_DIR={OUT_DIR}  WORK_DIR={WORK_DIR}  free={_free_gb(str(WORK_DIR)):.1f} GB")

# %%
# ---------------------------------------------------------------- helpers: results, shell, GPU
RESULTS = {
    "probe_version": PROBE_VERSION,
    "started_at": datetime.now(UTC).isoformat(),
    "env": {},
    "builds": {},
    "runs": [],
}


def save_results() -> None:
    RESULTS["updated_at"] = datetime.now(UTC).isoformat()
    tmp = RESULTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(RESULTS, indent=2))
    tmp.replace(RESULTS_PATH)


def sh(
    cmd: str, timeout: int = 3600, log: Path | None = None, check: bool = False
) -> subprocess.CompletedProcess:
    """Run a shell command, optionally teeing combined output to a log file."""
    print(f"$ {cmd}")
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    if log is not None:
        log.write_text(out)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {cmd}\n{out[-3000:]}")
    return proc


def time_left() -> float:
    return SESSION_BUDGET_S - (time.time() - T_START)


def gpu_mem_mib() -> list[int]:
    p = subprocess.run(
        "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits",
        shell=True,
        capture_output=True,
        text=True,
    )
    try:
        return [int(x.strip()) for x in p.stdout.strip().splitlines()]
    except ValueError:
        return []


class GpuPeakSampler:
    """Polls nvidia-smi in the background and keeps the per-GPU peak memory."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak: list[int] = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            cur = gpu_mem_mib()
            if cur:
                self.peak = (
                    cur if not self.peak else [max(a, b) for a, b in zip(self.peak, cur, strict=False)]
                )
            time.sleep(self.interval)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=5)


def wait_gpu_free(threshold_mib: int = 600, timeout: int = 120) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        mem = gpu_mem_mib()
        if not mem or max(mem) < threshold_mib:  # no GPU visible, or memory released
            return
        time.sleep(2)


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def tail(path: Path, n: int = 60) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


# %%
# ---------------------------------------------------------------- environment fingerprint
def fingerprint() -> dict:
    env = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "gpus": sh(
            "nvidia-smi --query-gpu=index,name,memory.total,compute_cap,driver_version --format=csv,noheader"
        )
        .stdout.strip()
        .splitlines(),
        "nvcc": sh("nvcc --version | tail -2").stdout.strip(),
        "gcc": sh("gcc --version | head -1").stdout.strip(),
        "cmake": sh("cmake --version | head -1").stdout.strip(),
        "ram_total_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1),
        "disk_free_gb": {
            p: round(_free_gb(p), 1) for p in ["/kaggle/working", "/kaggle/temp", "/tmp"] if Path(p).exists()
        },
        "work_dir": str(WORK_DIR),
    }
    try:
        import torch

        env["system_torch"] = torch.__version__
        env["system_torch_cuda"] = torch.version.cuda
    except Exception as e:
        env["system_torch"] = f"unavailable: {e}"
    return env


RESULTS["env"] = fingerprint()
save_results()
print(json.dumps(RESULTS["env"], indent=2))

# Optional HF token from Kaggle secrets (never printed or saved)
try:
    from kaggle_secrets import UserSecretsClient  # type: ignore

    os.environ["HF_TOKEN"] = UserSecretsClient().get_secret("HF_TOKEN")
    print("HF_TOKEN loaded from Kaggle secrets")
except Exception:
    print("No HF_TOKEN secret (anonymous downloads)")

sh(f"{sys.executable} -m pip install -q -U huggingface_hub requests", timeout=900)

# %%
# ---------------------------------------------------------------- client-side measurements
import requests

SMOKE_PROMPT = (
    "Write a C99 function with exactly this signature:\n"
    "uint16_t crc16_ccitt_false(const uint8_t *data, size_t len);\n"
    "It computes CRC-16/CCITT-FALSE: polynomial 0x1021, initial value 0xFFFF, no input or output "
    "reflection, final XOR 0x0000. Include the #include lines it needs. Do not write a main function. "
    "Reply with a single C code block and nothing else."
)
SMOKE_HARNESS = r"""
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
uint16_t crc16_ccitt_false(const uint8_t *data, size_t len);
int main(void) {
    const uint8_t v1[] = {'1','2','3','4','5','6','7','8','9'};
    const uint8_t v2[] = {0x00};
    const uint8_t v3[] = {0xFF, 0xFF, 0xFF, 0xFF};
    int ok = 1;
    ok &= crc16_ccitt_false(v1, sizeof v1) == 0x29B1;
    ok &= crc16_ccitt_false(v2, 0) == 0xFFFF;
    ok &= crc16_ccitt_false(v2, sizeof v2) == 0xE1F0;
    ok &= crc16_ccitt_false(v3, sizeof v3) == 0x1D0F;
    puts(ok ? "PASS" : "FAIL");
    return ok ? 0 : 1;
}
"""


def _long_prompt() -> str:
    """~6k-token synthetic C source, used to measure prefill (prompt processing) speed."""
    funcs = []
    for i in range(160):
        funcs.append(
            f"static int32_t filter_stage_{i}(int32_t x, int32_t k) {{\n"
            f"    int32_t acc = (x * {i % 7 + 1}) >> 2;\n"
            f"    if (acc > k) {{ acc = k - {i}; }} else {{ acc += {i * 3}; }}\n"
            f"    return acc ^ 0x{i:04X};\n}}\n"
        )
    return (
        "Here is a C file:\n```c\n"
        + "\n".join(funcs)
        + "```\nIn one sentence, what do these functions have in common?"
    )


LONG_PROMPT = _long_prompt()


def chat_stream(
    base: str, model: str, prompt: str, max_tokens: int, extra: dict | None = None, timeout: int = 900
) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if extra:
        payload.update(extra)
    t0 = time.perf_counter()
    t_first = None
    n_chunks = 0
    text: list[str] = []
    usage = None
    with requests.post(f"{base}/v1/chat/completions", json=payload, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                break
            obj = json.loads(data)
            if obj.get("usage"):
                usage = obj["usage"]
            for ch in obj.get("choices") or []:
                delta = ch.get("delta") or {}
                content = delta.get("content") or ""
                reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if content or reasoning:
                    if t_first is None:
                        t_first = time.perf_counter()
                    n_chunks += 1
                if content:
                    text.append(content)
    t1 = time.perf_counter()
    completion_tokens = (usage or {}).get("completion_tokens") or n_chunks
    prompt_tokens = (usage or {}).get("prompt_tokens")
    ttft = (t_first - t0) if t_first else None
    decode_window = (t1 - t_first) if t_first else None
    return {
        "ttft_s": round(ttft, 3) if ttft else None,
        "total_s": round(t1 - t0, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "decode_tps": round((completion_tokens - 1) / decode_window, 2)
        if decode_window and completion_tokens > 1
        else None,
        "prefill_tps": round(prompt_tokens / ttft, 1) if (prompt_tokens and ttft) else None,
        "usage_reported": usage is not None,
        "text": "".join(text),
    }


def extract_code(text: str) -> str:
    blocks = re.findall(r"```[a-zA-Z0-9+]*\s*\n(.*?)```", text, flags=re.S)
    return max(blocks, key=len) if blocks else text


def smoke_test(base: str, model: str, extra: dict | None, tag: str) -> dict:
    res = chat_stream(base, model, SMOKE_PROMPT, max_tokens=1024, extra=extra)
    d = WORK_DIR / f"smoke_{tag}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "solution.c").write_text(extract_code(res["text"]))
    (d / "harness.c").write_text(SMOKE_HARNESS)
    comp = subprocess.run(
        f"gcc -std=c99 -Wall -Wextra -O2 {d / 'solution.c'} {d / 'harness.c'} -o {d / 't'}",
        shell=True,
        capture_output=True,
        text=True,
    )
    warnings = len(re.findall(r"warning:", comp.stderr))
    passed = False
    if comp.returncode == 0:
        run = subprocess.run(str(d / "t"), shell=True, capture_output=True, text=True, timeout=10)
        passed = run.returncode == 0 and "PASS" in run.stdout
    (LOG_DIR / f"smoke_{tag}.txt").write_text(res["text"] + "\n\n--- gcc ---\n" + comp.stderr)
    return {
        "compiled": comp.returncode == 0,
        "warnings": warnings,
        "passed": passed,
        "ttft_s": res["ttft_s"],
        "decode_tps": res["decode_tps"],
        "completion_tokens": res["completion_tokens"],
    }


def concurrency_test(base: str, model: str, extra: dict | None, n: int) -> dict:
    prompts = [
        f"Write a C99 function that implements a fixed-size ring buffer push operation (variant {i}). "
        "Explain each line briefly."
        for i in range(n)
    ]
    out: list[dict | None] = [None] * n

    def worker(i: int) -> None:
        try:
            out[i] = chat_stream(base, model, prompts[i], max_tokens=256, extra=extra)
        except Exception as e:
            out[i] = {"error": str(e)}

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    ok = [o for o in out if o and "error" not in o]
    total_tokens = sum(o["completion_tokens"] for o in ok)
    return {
        "n_requests": n,
        "n_ok": len(ok),
        "wall_s": round(wall, 2),
        "aggregate_tps": round(total_tokens / wall, 2) if wall > 0 else None,
        "mean_ttft_s": round(sum(o["ttft_s"] for o in ok if o["ttft_s"]) / max(1, len(ok)), 3)
        if ok
        else None,
        "per_request_decode_tps": [o["decode_tps"] for o in ok],
        "errors": [o["error"] for o in out if o and "error" in o],
    }


# %%
# ---------------------------------------------------------------- server process management
class Server:
    def __init__(self, cmd: list[str], log_path: Path, env: dict | None = None):
        self.cmd = cmd
        self.log_path = log_path
        self.env = {**os.environ, **(env or {})}
        self.proc: subprocess.Popen | None = None
        self._log = None

    def start(self) -> None:
        assert port_free(SERVER_PORT), f"port {SERVER_PORT} busy"
        self._log = open(self.log_path, "w")
        self._log.write("$ " + " ".join(self.cmd) + "\n")
        self._log.flush()
        self.proc = subprocess.Popen(
            self.cmd, stdout=self._log, stderr=subprocess.STDOUT, env=self.env, start_new_session=True
        )

    def wait_ready(self, timeout: int) -> tuple[bool, str]:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                return False, f"process exited with code {self.proc.returncode}"
            try:
                r = requests.get(f"http://127.0.0.1:{SERVER_PORT}/health", timeout=5)
                if r.status_code == 200:
                    return True, "ok"
            except requests.RequestException:
                pass
            time.sleep(3)
        return False, f"not ready after {timeout}s"

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=45)
            except Exception:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except Exception:
                    pass
        if self._log:
            self._log.close()
        wait_gpu_free()


def measure_server(
    engine: str,
    base: str,
    model_name: str,
    cand: dict,
    tag: str,
    do_smoke: bool,
    do_single: bool,
    do_prefill: bool,
    do_concurrency: bool,
) -> dict:
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if cand["disable_thinking"] else None
    m: dict = {"vram_idle_mib": gpu_mem_mib()}
    with GpuPeakSampler() as sampler:
        if do_smoke:
            try:
                m["smoke"] = smoke_test(base, model_name, extra, f"{engine}_{tag}")
            except Exception as e:
                m["smoke"] = {"error": str(e)}
        if do_single:
            try:
                r = chat_stream(
                    base,
                    model_name,
                    "Explain what a watchdog timer is in an embedded system, in about 200 words.",
                    max_tokens=320,
                    extra=extra,
                )
                r.pop("text", None)
                m["single_stream"] = r
            except Exception as e:
                m["single_stream"] = {"error": str(e)}
        if do_prefill:
            try:
                r = chat_stream(base, model_name, LONG_PROMPT, max_tokens=48, extra=extra)
                r.pop("text", None)
                m["prefill"] = r
            except Exception as e:
                m["prefill"] = {"error": str(e)}
        if do_concurrency:
            try:
                m["concurrency"] = concurrency_test(base, model_name, extra, CONCURRENCY)
            except Exception as e:
                m["concurrency"] = {"error": str(e)}
    m["vram_peak_mib"] = sampler.peak
    return m


# %%
# ---------------------------------------------------------------- build llama.cpp (CUDA, SM 7.5)
LLAMA_DIR = WORK_DIR / "llama.cpp"
LLAMA_SERVER = LLAMA_DIR / "build" / "bin" / "llama-server"

if RUN_LLAMACPP:
    t0 = time.time()
    build_log = LOG_DIR / "llamacpp_build.log"
    try:
        if not LLAMA_SERVER.exists():
            ref = f"--branch {LLAMACPP_REF}" if LLAMACPP_REF else ""
            sh(f"git clone --depth 1 {ref} {LLAMACPP_GIT} {LLAMA_DIR}", check=True, timeout=600)
            nproc = os.cpu_count() or 4
            sh(
                f"cd {LLAMA_DIR} && export PATH=/usr/local/cuda/bin:$PATH && "
                f"cmake -S . -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75 -DLLAMA_CURL=OFF "
                f"-DCMAKE_BUILD_TYPE=Release && "
                f"cmake --build build --config Release -j{nproc} --target llama-server",
                log=build_log,
                check=True,
                timeout=5400,
            )
        commit = sh(f"git -C {LLAMA_DIR} rev-parse HEAD").stdout.strip()
        RESULTS["builds"]["llamacpp"] = {"ok": True, "commit": commit, "build_s": round(time.time() - t0)}
    except Exception as e:
        RESULTS["builds"]["llamacpp"] = {"ok": False, "error": str(e)[-2000:], "log_tail": tail(build_log)}
        RUN_LLAMACPP = False
    save_results()
    print(RESULTS["builds"]["llamacpp"])

# %%
# ---------------------------------------------------------------- GGUF resolution & download
from huggingface_hub import HfApi, hf_hub_download

_api = HfApi()


def resolve_gguf(repo: str, quant: str) -> list[str]:
    """Return the GGUF file(s) for a quant (all shards if split), preferring non-'UD' files."""
    files = _api.list_repo_files(repo)
    pat = re.compile(rf"(^|[-_./]){re.escape(quant)}([-_.]|$)", re.I)
    ggufs = [f for f in files if f.endswith(".gguf") and "mmproj" not in f.lower() and pat.search(f)]
    if not ggufs:
        raise FileNotFoundError(
            f"no {quant} GGUF in {repo}; available: {sorted({f for f in files if f.endswith('.gguf')})[:20]}"
        )
    plain = [f for f in ggufs if "UD-" not in f] or ggufs
    # group shards: name-00001-of-00003.gguf
    first = sorted(plain)[0]
    m = re.match(r"(.*)-\d{5}-of-(\d{5})\.gguf$", first)
    if m:
        prefix = m.group(1)
        return sorted(f for f in plain if f.startswith(prefix) and re.search(r"-\d{5}-of-\d{5}\.gguf$", f))
    return [first]


def gguf_local_dir(repo: str) -> Path:
    return MODELS_DIR / repo.replace("/", "__")


def download_gguf(repo: str, files: list[str]) -> Path:
    paths = [Path(hf_hub_download(repo, f, local_dir=gguf_local_dir(repo))) for f in files]
    return sorted(paths)[0]


_llama_help = ""


def llama_supports(flag: str) -> bool:
    global _llama_help
    if not _llama_help:
        p = sh(f"{LLAMA_SERVER} --help", timeout=120)
        _llama_help = p.stdout + p.stderr
    return flag in _llama_help


# %%
# ---------------------------------------------------------------- llama.cpp leg
def run_llamacpp(cand: dict) -> None:
    run = {
        "engine": "llama.cpp",
        "model_key": cand["key"],
        "family": cand["family"],
        "arch": cand["arch"],
        "repo": cand["gguf_repo"],
        "quant": cand["gguf_quant"],
        "launches": [],
        "status": "started",
    }
    RESULTS["runs"].append(run)
    save_results()
    try:
        files = resolve_gguf(cand["gguf_repo"], cand["gguf_quant"])
        run["files"] = files
        t0 = time.time()
        model_path = download_gguf(cand["gguf_repo"], files)
        run["download_s"] = round(time.time() - t0)
        run["file_size_gb"] = round(
            sum(p.stat().st_size for p in gguf_local_dir(cand["gguf_repo"]).rglob("*.gguf")) / 1e9, 2
        )
        save_results()
    except Exception as e:
        run["status"] = "download_failed"
        run["error"] = str(e)[-1500:]
        save_results()
        shutil.rmtree(gguf_local_dir(cand["gguf_repo"]), ignore_errors=True)
        return

    for label, n_par, ctx in LLAMACPP_LAUNCHES:
        if time_left() < 1800:
            run["launches"].append({"label": label, "skipped": "session time budget"})
            break
        log = LOG_DIR / f"llamacpp_{cand['key']}_{label}.log"
        cmd = [
            str(LLAMA_SERVER),
            "-m",
            str(model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(SERVER_PORT),
            "-ngl",
            "999",
            "-c",
            str(ctx),
            "--parallel",
            str(n_par),
            "--jinja",
            "--metrics",
        ]
        if cand["disable_thinking"] and llama_supports("--reasoning-budget"):
            cmd += ["--reasoning-budget", "0"]
        launch = {"label": label, "n_parallel": n_par, "ctx_total": ctx, "cmd": " ".join(cmd[1:])}
        srv = Server(cmd, log)
        t0 = time.time()
        srv.start()
        ok, why = srv.wait_ready(timeout=900)
        launch["load_s"] = round(time.time() - t0, 1)
        launch["loaded"] = ok
        if not ok:
            launch["error"] = why
            launch["log_tail"] = tail(log, 40)
            srv.stop()
            run["launches"].append(launch)
            save_results()
            continue
        try:
            launch.update(
                measure_server(
                    "llamacpp",
                    f"http://127.0.0.1:{SERVER_PORT}",
                    "probe",
                    cand,
                    f"{cand['key']}_{label}",
                    do_smoke=(label == "single_16k"),
                    do_single=(label != "concurrent_4x8k"),
                    do_prefill=(label == "single_16k"),
                    do_concurrency=(label == "concurrent_4x8k"),
                )
            )
        finally:
            srv.stop()
        run["launches"].append(launch)
        save_results()

    run["status"] = "done" if any(l.get("loaded") for l in run["launches"]) else "load_failed"
    save_results()
    shutil.rmtree(gguf_local_dir(cand["gguf_repo"]), ignore_errors=True)


if RUN_LLAMACPP:
    for cand in CANDIDATES:
        if time_left() < 2400:
            print("Stopping llama.cpp leg: session time budget")
            break
        print(f"\n=== llama.cpp :: {cand['key']}")
        run_llamacpp(cand)
        print(json.dumps({k: v for k, v in RESULTS["runs"][-1].items() if k != "launches"}, indent=1))

# %%
# ---------------------------------------------------------------- vLLM install (isolated venv)
VLLM_VENV = WORK_DIR / "vllm-venv"
VLLM_BIN = VLLM_VENV / "bin" / "vllm"
_vllm_help = ""

if RUN_VLLM and any(c["vllm_repos"] for c in CANDIDATES) and time_left() > 3600:
    t0 = time.time()
    log = LOG_DIR / "vllm_install.log"
    try:
        sh(f"{sys.executable} -m pip install -q uv", check=True, timeout=600)
        sh(
            f"uv venv {VLLM_VENV} --python 3.12 --seed",
            check=True,
            timeout=900,
            log=LOG_DIR / "vllm_venv.log",
        )
        sh(
            f"uv pip install --python {VLLM_VENV}/bin/python {VLLM_PIP_SPEC}",
            check=True,
            timeout=2400,
            log=log,
        )
        ver = sh(
            f"{VLLM_VENV}/bin/python -c 'import vllm, torch; print(vllm.__version__, torch.__version__, "
            f"torch.version.cuda)'",
            timeout=600,
        ).stdout.strip()
        RESULTS["builds"]["vllm"] = {"ok": True, "versions": ver, "install_s": round(time.time() - t0)}
        hp = sh(f"{VLLM_BIN} serve --help=all", timeout=600)
        _vllm_help = hp.stdout + hp.stderr
        if len(_vllm_help) < 2000:
            hp = sh(f"{VLLM_BIN} serve --help", timeout=600)
            _vllm_help = hp.stdout + hp.stderr
    except Exception as e:
        RESULTS["builds"]["vllm"] = {"ok": False, "error": str(e)[-2000:], "log_tail": tail(log)}
        RUN_VLLM = False
    save_results()
    print(RESULTS["builds"].get("vllm"))
else:
    RUN_VLLM = False


def parse_vllm_log(text: str) -> dict:
    info = {}
    m = re.search(r"GPU KV cache size:\s*([\d,]+)\s*tokens", text)
    if m:
        info["kv_cache_tokens"] = int(m.group(1).replace(",", ""))
    m = re.search(r"Maximum concurrency for\s*([\d,]+)\s*tokens per request:\s*([\d.]+)x", text)
    if m:
        info["max_concurrency_at_len"] = {"tokens": int(m.group(1).replace(",", "")), "x": float(m.group(2))}
    m = re.search(r"Model loading took\s*([\d.]+)\s*Gi?B", text)
    if m:
        info["weights_gib_per_rank"] = float(m.group(1))
    backends = sorted(set(re.findall(r"Using\s+([A-Za-z0-9_.]+)\s+(?:attention\s+)?backend", text)))
    if backends:
        info["backends"] = backends
    m = re.search(r"quantization=([a-zA-Z0-9_]+)", text)
    if m:
        info["quantization"] = m.group(1)
    return info


# %%
# ---------------------------------------------------------------- vLLM leg
def run_vllm(cand: dict) -> None:
    for repo in cand["vllm_repos"]:
        for enforce_eager in (False, True):
            if time_left() < 2400:
                return
            extra = list(cand["vllm_extra"])
            for flag_pair in cand["vllm_extra_if_supported"]:
                if flag_pair[0] in _vllm_help:
                    extra += flag_pair
            if enforce_eager:
                extra.append("--enforce-eager")
            cmd = [
                str(VLLM_BIN),
                "serve",
                repo,
                "--host",
                "127.0.0.1",
                "--port",
                str(SERVER_PORT),
                "--served-model-name",
                "probe",
                "--tensor-parallel-size",
                "2",
                "--dtype",
                "half",
                "--max-model-len",
                str(VLLM_MAX_MODEL_LEN),
                "--gpu-memory-utilization",
                str(VLLM_GPU_MEM_UTIL),
                "--trust-remote-code",
                *extra,
            ]
            tag = f"{cand['key']}__{repo.split('/')[0]}__{'eager' if enforce_eager else 'graphs'}"
            log = LOG_DIR / f"vllm_{tag}.log"
            run = {
                "engine": "vllm",
                "model_key": cand["key"],
                "family": cand["family"],
                "arch": cand["arch"],
                "repo": repo,
                "enforce_eager": enforce_eager,
                "cmd": " ".join(cmd[1:]),
                "status": "started",
            }
            RESULTS["runs"].append(run)
            save_results()
            srv = Server(cmd, log, env={"HF_HOME": str(HF_HOME), "VLLM_LOGGING_LEVEL": "INFO"})
            t0 = time.time()
            srv.start()
            ok, why = srv.wait_ready(timeout=2400)  # includes download + weight loading + compilation
            run["load_s"] = round(time.time() - t0, 1)
            run["log_info"] = parse_vllm_log(log.read_text(errors="replace"))
            if not ok:
                run["status"] = "load_failed"
                run["error"] = why
                run["log_tail"] = tail(log, 60)
                srv.stop()
                save_results()
                continue
            try:
                run.update(
                    measure_server(
                        "vllm",
                        f"http://127.0.0.1:{SERVER_PORT}",
                        "probe",
                        cand,
                        tag,
                        do_smoke=True,
                        do_single=True,
                        do_prefill=True,
                        do_concurrency=True,
                    )
                )
                run["status"] = "done"
            finally:
                srv.stop()
                run["log_info"] = parse_vllm_log(log.read_text(errors="replace"))
                save_results()
            shutil.rmtree(HF_HOME / "hub", ignore_errors=True)
            return  # first working configuration is enough for the probe
        shutil.rmtree(HF_HOME / "hub", ignore_errors=True)


if RUN_VLLM:
    for cand in CANDIDATES:
        if cand["vllm_repos"]:
            print(f"\n=== vLLM :: {cand['key']}")
            run_vllm(cand)


# %%
# ---------------------------------------------------------------- report
def _fmt(v, nd=1):
    return "—" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def build_report() -> str:
    env = RESULTS["env"]
    lines = [
        "# Probe report — Kaggle 2× Tesla T4",
        "",
        f"- Probe version: `{PROBE_VERSION}` · started {RESULTS['started_at']} · updated {RESULTS.get('updated_at')}",
        f"- GPUs: {env.get('gpus')}",
        f"- CUDA: {env.get('nvcc')} · Python {env.get('python')} · CPUs {env.get('cpu_count')} · "
        f"RAM {env.get('ram_total_gb')} GB",
        f"- llama.cpp: {RESULTS['builds'].get('llamacpp')}",
        f"- vLLM: {RESULTS['builds'].get('vllm')}",
        "",
        "## Results",
        "",
        "| Engine | Model | Config | Loaded | Load s | VRAM idle (MiB) | VRAM peak (MiB) | TTFT s | Decode tok/s "
        "| Prefill tok/s | 4× agg tok/s | Smoke C test |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in RESULTS["runs"]:
        rows = run.get("launches") if run["engine"] == "llama.cpp" else [run]
        if run["engine"] == "llama.cpp" and not rows:
            lines.append(
                f"| llama.cpp | {run['model_key']} | — | ✗ | — | — | — | — | — | — | — | "
                f"{run.get('status')}: {str(run.get('error', ''))[:80]} |"
            )
            continue
        for r in rows:
            cfg = (
                r.get("label")
                or ("eager" if r.get("enforce_eager") else "cuda-graphs") + f" · {r.get('repo')}"
            )
            loaded = r.get("loaded", r.get("status") == "done")
            ss, pf, cc, sm = (
                r.get("single_stream", {}),
                r.get("prefill", {}),
                r.get("concurrency", {}),
                r.get("smoke", {}),
            )
            smoke = (
                "—"
                if not sm
                else ("✓ pass" if sm.get("passed") else ("compiled, wrong" if sm.get("compiled") else "✗"))
            )
            lines.append(
                f"| {run['engine']} | {run['model_key']} | {cfg} | {'✓' if loaded else '✗'} | {_fmt(r.get('load_s'))} "
                f"| {r.get('vram_idle_mib', '—')} | {r.get('vram_peak_mib', '—')} | {_fmt(ss.get('ttft_s'), 2)} "
                f"| {_fmt(ss.get('decode_tps'))} | {_fmt(pf.get('prefill_tps'))} | {_fmt(cc.get('aggregate_tps'))} "
                f"| {smoke} |"
            )
    failures = [r for r in RESULTS["runs"] if r.get("status") not in ("done",)]
    if failures:
        lines += ["", "## Failures (log tails)", ""]
        for r in failures:
            lines += [
                f"### {r['engine']} · {r['model_key']} · {r.get('repo')}",
                "",
                "```",
                str(r.get("error", ""))[:500],
                (r.get("log_tail") or "")[-2500:],
                "```",
                "",
            ]
    return "\n".join(lines)


REPORT_PATH.write_text(build_report())
save_results()
print(REPORT_PATH.read_text())
print(f"\nTotal elapsed: {(time.time() - T_START) / 3600:.2f} h")
