# %% [markdown]
# # 01 · M1 benchmark — serving, sizing calibration and hybrid traceability (Kaggle 2× T4)
#
# One GPU session produces every measured number of milestone M1:
#
# 1. **Serving benchmark** — for each shortlisted (model, engine) configuration: three code-assistant traffic
#    profiles (inline completion, IDE chat, agent step with shared prefix) × concurrency sweep → TTFT, TPOT,
#    throughput percentiles, peak VRAM per GPU.
# 2. **Sizing inputs** — exact architecture configs (`config.json`, GGUF metadata, checkpoint sizes) used to
#    complete and calibrate `oge sizing`.
# 3. **Traceability recovery** — dense retrieval (Qwen3-Embedding-0.6B), hybrid graph + lexical + dense fusion,
#    and LLM reranking with a served model, on 151 F´ requirements / 3,261 candidate tests.
#
# **How to run (≈ 3–4 h of GPU quota):** Kaggle → *Import Notebook* → this file · *Session options*:
# **GPU T4 ×2**, **Internet On** · *Save Version* → **Save & Run All (Commit)**. Download the `m1/` output folder.
# Every stage writes its results immediately; a failure in one configuration does not stop the others.

# %%
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

DRY_RUN = os.environ.get("M1_DRY_RUN") == "1"  # local validation: no installs, no GPU stages
REPO_URL = "https://github.com/__GITHUB_USER__/onprem-genai-embedded"
REPO_REF = "main"
SESSION_BUDGET_S = 10.5 * 3600
T0 = time.time()

# Shortlist from kaggle/00 probe results (docs/results/probe/). Each entry = one served configuration.
CONFIGS = [
    {
        "key": "qwen3-coder-30b-a3b__llamacpp",
        "model": "qwen3-coder-30b-a3b",
        "engine": "llama.cpp",
        "gguf_repo": "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF",
        "quant": "Q4_K_M",
        "parallel": 8,
        "ctx_per_slot": 16384,
        "disable_thinking": False,
    },
    {
        "key": "qwen3-coder-30b-a3b__vllm",
        "model": "qwen3-coder-30b-a3b",
        "engine": "vllm",
        "hf_repo": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ",
        "max_model_len": 16384,
        "extra": ["--enable-expert-parallel"],
        "disable_thinking": False,
    },
    {
        "key": "devstral-small-2-24b__llamacpp",
        "model": "devstral-small-2-24b",
        "engine": "llama.cpp",
        "gguf_repo": "unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF",
        "quant": "Q4_K_M",
        "parallel": 4,
        "ctx_per_slot": 16384,
        "disable_thinking": False,
    },
    {
        "key": "qwen3.8-27b__llamacpp",
        "model": "qwen3.8-27b",
        "engine": "llama.cpp",
        "gguf_repo": "unsloth/Qwen3.8-27B-GGUF",
        "quant": "Q4_K_M",
        "parallel": 4,
        "ctx_per_slot": 16384,
        "disable_thinking": True,
    },
]
JUDGE_CONFIG = "qwen3-coder-30b-a3b__llamacpp"  # served model used for LLM reranking
PROFILES = ["completion", "chat", "agent"]
CONCURRENCY = [1, 2, 4, 8, 16]
MIN_REQUESTS_PER_LEVEL = 8
EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
PORT = 8080

# Official repos whose config.json / safetensors index complete the sizing specs.
CONFIG_REPOS = {
    "qwen3.8-27b": ["Qwen/Qwen3.8-27B", "unsloth/Qwen3.8-27B-GGUF"],
    "qwen3-coder-30b-a3b": ["Qwen/Qwen3-Coder-30B-A3B-Instruct"],
    "devstral-small-2-24b": ["mistralai/Devstral-Small-2-24B-Instruct-2512"],
    "qwen3.6-35b-a3b": ["Qwen/Qwen3.6-35B-A3B"],
    "deepseek-v4-flash": ["deepseek-ai/DeepSeek-V4-Flash"],
    "deepseek-v4-pro": ["deepseek-ai/DeepSeek-V4-Pro"],
    "deepseek-v3.2": ["deepseek-ai/DeepSeek-V3.2", "deepseek-ai/DeepSeek-V3.2-Exp"],
}

OUT = Path("/kaggle/working/m1") if Path("/kaggle/working").exists() else Path.cwd() / "m1"
LOGS = OUT / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
scratch = [p for p in ("/kaggle/temp", "/tmp") if Path(p).exists()]
WORK = Path(max(scratch, key=lambda p: shutil.disk_usage(p).free)) / "m1_work"
WORK.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"] = str(WORK / "hf")


def save(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, indent=2, default=str))


def time_left() -> float:
    return SESSION_BUDGET_S - (time.time() - T0)


try:
    from kaggle_secrets import UserSecretsClient  # type: ignore

    os.environ["HF_TOKEN"] = UserSecretsClient().get_secret("HF_TOKEN")
except Exception:
    pass

# %%
# ---------------------------------------------------------------- install this project (pinned ref)
if not DRY_RUN:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=True)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            sys.executable,
            "-q",
            f"onprem-genai-embedded[knowledge,bench] @ git+{REPO_URL}@{REPO_REF}",
            "sentence-transformers>=3.0",
            "transformers>=4.51",
        ],
        check=True,
    )
_remote = subprocess.run(
    ["git", "ls-remote", REPO_URL, REPO_REF], capture_output=True, text=True
).stdout.split()
repo_commit = _remote[0] if _remote else "unknown"

from onprem_genai.bench import engines as E  # noqa: N812
from onprem_genai.bench.loadgen import run_blocking, run_level
from onprem_genai.bench.profiles import load_corpus, make_profiles
from onprem_genai.knowledge import traceability as tr
from onprem_genai.knowledge.fprime.ingest import ingest_fprime

env = {
    "started_at": datetime.now(UTC).isoformat(),
    "repo": REPO_URL,
    "repo_commit": repo_commit,
    "gpus": subprocess.run(
        "nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader",
        shell=True,
        capture_output=True,
        text=True,
    )
    .stdout.strip()
    .splitlines(),
    "python": sys.version.split()[0],
    "configs": CONFIGS,
}
save("env.json", env)

# %%
# ---------------------------------------------------------------- F´ knowledge graph (CPU, seconds)
FPRIME = Path(os.environ.get("M1_FPRIME", WORK / "fprime"))
if not FPRIME.exists():
    subprocess.run(
        [
            "git",
            "-c",
            "advice.detachedHead=false",
            "clone",
            "-q",
            "--depth",
            "1",
            "--branch",
            "v4.4.1",
            "https://github.com/nasa/fprime",
            str(FPRIME),
        ],
        check=True,
    )
graph, ingest_report = ingest_fprime(FPRIME)
ds = tr.build_dataset(graph)
print(
    f"graph: {graph.stats()}\ntraceability set: {len(ds.req_ids)} requirements, {len(ds.candidates)} candidates"
)

# %%
# ---------------------------------------------------------------- dense + hybrid traceability (GPU embeddings)
trace_results = {
    "dataset": {
        "requirements": len(ds.req_ids),
        "candidates": len(ds.candidates),
        "fprime_commit": graph.meta.get("commit"),
        "embedder": EMBED_MODEL,
    },
    "methods": {},
}
bm25 = tr.bm25_ranker(ds)
rankers = {"bm25": bm25, "graph": tr.graph_ranker(ds), "graph+bm25": tr.graph_constrained(ds, bm25)}
try:
    if DRY_RUN:
        raise RuntimeError("dry run: dense retrieval skipped")
    from onprem_genai.knowledge.retrieval import SentenceTransformerEmbedder

    emb = SentenceTransformerEmbedder(
        EMBED_MODEL, query_instruction=tr.QUERY_INSTRUCTION, device="cuda", max_seq_length=2048, batch=16
    )
    t = time.time()
    dense = tr.dense_ranker(ds, emb)
    trace_results["dataset"]["embedding_s"] = round(time.time() - t, 1)
    rankers["dense"] = dense
    rankers["graph+dense"] = tr.graph_constrained(ds, dense)
    rankers["graph+rrf(bm25,dense)"] = tr.graph_constrained(ds, tr.fused([bm25, dense]))
    del emb
    import torch

    torch.cuda.empty_cache()
except Exception:
    trace_results["dense_error"] = traceback.format_exc()[-3000:]
for name, rk in rankers.items():
    trace_results["methods"][name] = tr.evaluate(ds, rk)
    print(name, {k: v["mean"] for k, v in trace_results["methods"][name]["metrics"].items()})
save("traceability.json", trace_results)
best_hybrid_name = "graph+rrf(bm25,dense)" if "graph+rrf(bm25,dense)" in rankers else "graph+bm25"

# %%
# ---------------------------------------------------------------- architecture configs for sizing
from huggingface_hub import hf_hub_download

configs_dir = OUT / "model_configs"
configs_dir.mkdir(exist_ok=True)
config_log = {}
for model, repos in ({} if DRY_RUN else CONFIG_REPOS).items():
    for repo in repos:
        got = {}
        for fname in ("config.json", "model.safetensors.index.json"):
            try:
                p = hf_hub_download(repo, fname, local_dir=WORK / "cfg" / repo.replace("/", "__"))
                shutil.copy(p, configs_dir / f"{model}__{fname}")
                got[fname] = repo
            except Exception as e:  # gated or absent: recorded, not fatal
                got[fname] = f"error: {type(e).__name__}"
        config_log[model] = got
        if "config.json" in got and not str(got["config.json"]).startswith("error"):
            break
save("model_configs/sources.json", config_log)

# %%
# ---------------------------------------------------------------- engines
needs = set() if DRY_RUN else {c["engine"] for c in CONFIGS}
builds = {}
LLAMA_SERVER = VLLM = None
if "llama.cpp" in needs:
    try:
        LLAMA_SERVER = E.build_llamacpp(WORK, cuda_arch="75", log=LOGS / "llamacpp_build.log")
        builds["llama.cpp"] = subprocess.run(
            ["git", "-C", str(LLAMA_SERVER.parents[2]), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
    except Exception:
        builds["llama.cpp_error"] = traceback.format_exc()[-3000:]
if "vllm" in needs:
    try:
        VLLM = E.install_vllm(WORK, log=LOGS / "vllm_install.log")
        builds["vllm"] = subprocess.run(
            [str(VLLM.parent / "python"), "-c", "import vllm; print(vllm.__version__)"],
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        builds["vllm_error"] = traceback.format_exc()[-3000:]
save("builds.json", builds)
print(builds)

# %%
# ---------------------------------------------------------------- serving benchmark per configuration
corpus = load_corpus(FPRIME / "Svc")
profiles = make_profiles(corpus)


def launch(cfg):
    if cfg["engine"] == "llama.cpp":
        model_path = E.download_gguf(cfg["gguf_repo"], cfg["quant"], WORK / "models" / cfg["key"])
        meta = E.gguf_metadata(model_path)
        thinking_off = cfg.get("disable_thinking") and E.binary_supports(LLAMA_SERVER, "--reasoning-budget")
        extra = ["--reasoning-budget", "0"] if thinking_off else []
        cmd = E.llamacpp_command(
            LLAMA_SERVER,
            model_path,
            port=PORT,
            ctx_total=cfg["parallel"] * cfg["ctx_per_slot"],
            parallel=cfg["parallel"],
            extra=extra,
        )
        return E.ServerProcess(cmd, LOGS / f"{cfg['key']}.log", PORT), {"gguf_metadata": meta}
    cmd = E.vllm_command(
        VLLM,
        cfg["hf_repo"],
        port=PORT,
        tensor_parallel=2,
        max_model_len=cfg["max_model_len"],
        extra=cfg.get("extra", []),
    )
    return E.ServerProcess(cmd, LOGS / f"{cfg['key']}.log", PORT, env={"HF_HOME": os.environ["HF_HOME"]}), {}


for cfg in CONFIGS:
    if time_left() < 3600:
        print("stopping: session budget")
        break
    if (cfg["engine"] == "llama.cpp" and LLAMA_SERVER is None) or (cfg["engine"] == "vllm" and VLLM is None):
        continue
    res = {"config": cfg, "profiles": {}}
    srv = None
    try:
        t = time.time()
        srv, info = launch(cfg)
        res.update(info)
        srv.start()
        ok, why = srv.wait_ready(timeout_s=2400)
        res["load_s"] = round(time.time() - t, 1)
        if not ok:
            raise RuntimeError(f"server not ready: {why}\n{E.tail(srv.log_path)}")
        res["vram_idle_mib"] = E.gpu_memory_mib()
        if cfg["engine"] == "vllm":
            res["vllm_log"] = E.parse_vllm_log(srv.log_path.read_text(errors="replace"))
        extra = {"chat_template_kwargs": {"enable_thinking": False}} if cfg.get("disable_thinking") else None
        run_blocking(run_level(srv.base_url, "default", profiles["chat"], 1, 2, extra))  # warm-up
        for pname in PROFILES:
            levels = []
            for c in CONCURRENCY:
                with E.GpuPeakSampler() as sampler:
                    summary, _ = run_blocking(
                        run_level(
                            srv.base_url,
                            "default",
                            profiles[pname],
                            c,
                            max(MIN_REQUESTS_PER_LEVEL, 2 * c),
                            extra,
                        )
                    )
                levels.append({**summary.as_dict(), "vram_peak_mib": sampler.peak_mib})
                print(cfg["key"], pname, c, round(summary.output_tps, 1), "tok/s")
            res["profiles"][pname] = levels
            save(f"bench_{cfg['key']}.json", res)
        if cfg["key"] == JUDGE_CONFIG:
            judge = tr.LlmJudge(srv.base_url, "default", extra_body=extra)
            t = time.time()
            name = f"{best_hybrid_name}+llm-rerank@10"
            rerank = tr.llm_reranked(
                ds, rankers[best_hybrid_name], judge, top_n=10, max_workers=cfg.get("parallel", 8)
            )
            trace_results["methods"][name] = tr.evaluate(ds, rerank)
            trace_results["dataset"]["judge"] = {"config": cfg["key"], "seconds": round(time.time() - t, 1)}
            save("traceability.json", trace_results)
            print(name, {k: v["mean"] for k, v in trace_results["methods"][name]["metrics"].items()})
    except Exception:
        res["error"] = traceback.format_exc()[-4000:]
    finally:
        if srv is not None:
            srv.stop()
        shutil.rmtree(WORK / "models" / cfg["key"], ignore_errors=True)
        if cfg["engine"] == "vllm":
            shutil.rmtree(WORK / "hf" / "hub", ignore_errors=True)
        save(f"bench_{cfg['key']}.json", res)

# %%
# ---------------------------------------------------------------- summary
lines = [
    "# M1 benchmark summary",
    "",
    f"repo commit `{repo_commit}` · GPUs {env['gpus']}",
    "",
    "## Traceability recovery",
    "",
    "| method | MAP | MRR | R@1 | R@10 |",
    "|---|---|---|---|---|",
]
for name, r in trace_results["methods"].items():
    m = r["metrics"]
    lines.append(
        f"| {name} | {m['ap']['mean']:.3f} | {m['rr']['mean']:.3f} | {m['recall@1']['mean']:.3f} | "
        f"{m['recall@10']['mean']:.3f} |"
    )
lines += [
    "",
    "## Serving (chat profile)",
    "",
    "| config | conc. | out tok/s | TTFT p50 s | TPOT p50 ms |",
    "|---|---|---|---|---|",
]
for f in sorted(OUT.glob("bench_*.json")):
    r = json.loads(f.read_text())
    for lvl in r.get("profiles", {}).get("chat", []):
        lines.append(
            f"| {r['config']['key']} | {lvl['concurrency']} | {lvl['output_tps']:.1f} | "
            f"{(lvl['ttft_p50_s'] or 0):.2f} | {(lvl['tpot_p50_ms'] or 0):.1f} |"
        )
    if "error" in r:
        lines.append(f"| {r['config']['key']} | error | {r['error'].splitlines()[-1][:80]} | | |")
(OUT / "summary.md").write_text("\n".join(lines))
print("\n".join(lines))
print(f"elapsed {(time.time() - T0) / 3600:.2f} h")
