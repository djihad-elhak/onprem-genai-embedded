# %% [markdown]
# # 01 · Benchmark — serving, traceability, model evaluation and test-generation agent (Kaggle 2× T4)
#
# One GPU session produces every measured number of the project. Each shortlisted (model, engine)
# configuration is loaded **once** and goes through the stages listed in its `stages`:
#
# 1. **serving** — three code-assistant traffic profiles (inline completion, IDE chat, agent step with shared
#    prefix) × concurrency sweep → TTFT, TPOT, throughput percentiles, peak VRAM per GPU.
# 2. **eval** — `oge eval`: 27 embedded C tasks (generation, unit-test generation, refactoring, documentation)
#    scored by compiling and running them (hidden tests, sanitizers, gcov, mutants, complexity, Doxygen).
# 3. **agent** — the test-generation agent on the 28 F´ requirement gaps of the default benchmark: retrieve over
#    MCP, write a requirement-tagged unit test, build and run it with `fprime-util`, repair, commit; fault
#    detection on mutants of the code each test exercises.
#
# Also: dense + hybrid traceability recovery (Qwen3-Embedding-0.6B on GPU) with LLM reranking by `JUDGE_CONFIG`,
# and the official architecture configs used to complete the sizing calculator.
#
# **How to run (≈ 6–9 h of GPU quota; it stops cleanly before Kaggle's 12 h limit):** Kaggle → *File → Import
# Notebook* → this file · *Session options*: **GPU T4 ×2**, **Internet On** · *Save Version* → **Save & Run All
# (Commit)**. Download the `bench/` output folder. Every stage writes its results as soon as it finishes; a failure
# in one configuration or stage does not stop the others.

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

DRY_RUN = os.environ.get("BENCH_DRY_RUN") == "1"  # local check: no installs, no GPU, scripted / oracle models
REPO_URL = "https://github.com/__GITHUB_USER__/onprem-genai-embedded"
REPO_REF = "main"
SESSION_BUDGET_S = 11.0 * 3600
T0 = time.time()

# Shortlist from the kaggle/00 probe (docs/results/probe/). Each entry = one served configuration.
# Probe run 1: Qwen3-Coder-30B-A3B AWQ on vLLM works (98.8 tok/s single stream); llama.cpp entries are
# confirmed or replaced after probe run 2 (llama.cpp build fixed in probe 0.2.0).
CONFIGS = [
    {
        "key": "qwen3-coder-30b-a3b__vllm",
        "model": "qwen3-coder-30b-a3b",
        "engine": "vllm",
        "hf_repo": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ",
        "max_model_len": 20480,
        "extra": ["--enable-expert-parallel"],
        "parallel": 8,
        "disable_thinking": False,
        "stages": ["serving", "eval", "agent"],
    },
    {
        "key": "qwen3.8-27b__llamacpp",
        "model": "qwen3.8-27b",
        "engine": "llama.cpp",
        "gguf_repo": "unsloth/Qwen3.8-27B-GGUF",
        "quant": "Q4_K_M",
        "parallel": 4,
        "ctx_per_slot": 20480,
        "disable_thinking": True,
        "stages": ["serving", "eval", "agent"],
    },
    {
        "key": "devstral-small-2-24b__llamacpp",
        "model": "devstral-small-2-24b",
        "engine": "llama.cpp",
        "gguf_repo": "unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF",
        "quant": "Q4_K_M",
        "parallel": 4,
        "ctx_per_slot": 20480,
        "disable_thinking": False,
        "stages": ["serving", "eval"],
    },
]
JUDGE_CONFIG = "qwen3-coder-30b-a3b__vllm"  # served model used for LLM reranking of traceability candidates
PROFILES = ["completion", "chat", "agent"]
CONCURRENCY = [1, 2, 4, 8, 16]
MIN_REQUESTS_PER_LEVEL = 8
EVAL_SAMPLES = 1  # samples per task (pass@1); raise for pass@k if time allows
AGENT_MUTANTS = 4  # fault-detection mutants per verified requirement
AGENT_MAX_ATTEMPTS = 3
MIN_TIME_FOR_AGENT_S = 3600  # do not start an agent stage with less session time left
EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
PORT = 8080
FPRIME_TOOLS = ["fprime-tools==4.4.0", "fprime-fpp==3.4.0", "cmake==3.26.0", "ninja==1.11.1.4"]

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

OUT = Path("/kaggle/working/bench") if Path("/kaggle/working").exists() else Path.cwd() / "bench"
LOGS = OUT / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
scratch = [p for p in ("/kaggle/temp", "/tmp") if Path(p).exists()]
WORK = Path(max(scratch, key=lambda p: shutil.disk_usage(p).free)) / "bench_work"
WORK.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"] = str(WORK / "hf")


def save(name: str, obj) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))


def time_left() -> float:
    return SESSION_BUDGET_S - (time.time() - T0)


def run(cmd: list[str], log: Path | None = None, **kw) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if log is not None:
        log.write_text(p.stdout + p.stderr)
    return p


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
            f"onprem-genai-embedded[knowledge,bench,eval,agent] @ git+{REPO_URL}@{REPO_REF}",
            "sentence-transformers>=3.0",
            "transformers>=4.51",
        ],
        check=True,
    )
_remote = run(["git", "ls-remote", REPO_URL, REPO_REF]).stdout.split()
repo_commit = _remote[0] if _remote else "unknown"

from onprem_genai.agent.fprime import UT_BUILD_DIR, FprimeWorkspace
from onprem_genai.agent.graph import AgentConfig, AgentDeps
from onprem_genai.agent.knowledge import KnowledgeClient
from onprem_genai.agent.runner import DEFAULT_MODULES, ScriptedModel, run_batch, select_targets, summarize
from onprem_genai.bench import engines as E  # noqa: N812
from onprem_genai.bench.loadgen import run_blocking, run_level
from onprem_genai.bench.profiles import load_corpus, make_profiles
from onprem_genai.evalsuite import runner as evalrunner
from onprem_genai.evalsuite.tasks import load_tasks
from onprem_genai.knowledge import traceability as tr
from onprem_genai.knowledge.fprime.ingest import ingest_fprime
from onprem_genai.knowledge.store import InMemoryStore
from onprem_genai.llm import ChatModel
from onprem_genai.mcp_server.server import build_server

env = {
    "started_at": datetime.now(UTC).isoformat(),
    "repo": REPO_URL,
    "repo_commit": repo_commit,
    "gpus": run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    .stdout.strip()
    .splitlines()
    if shutil.which("nvidia-smi")
    else [],
    "python": sys.version.split()[0],
    "cpus": os.cpu_count(),
    "configs": CONFIGS,
}
save("env.json", env)

# %%
# ---------------------------------------------------------------- F´: checkout, unit-test toolchain, graph
FPRIME = Path(os.environ.get("BENCH_FPRIME", WORK / "fprime"))
if not FPRIME.exists():
    run(
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
if not (FPRIME / "googletest" / "CMakeLists.txt").exists():
    run(["git", "-C", str(FPRIME), "submodule", "update", "--init", "--depth", "1", "googletest"], check=True)

fprime_util = os.environ.get("BENCH_FPRIME_UTIL")
if not fprime_util and not DRY_RUN:
    venv = WORK / "fprime-venv"
    if not (venv / "bin" / "fprime-util").exists():
        run(["uv", "venv", str(venv), "--python", "3.12", "--seed"], check=True)
        run(["uv", "pip", "install", "--python", str(venv / "bin" / "python"), *FPRIME_TOOLS], check=True)
    fprime_util = str(venv / "bin" / "fprime-util")
ws = FprimeWorkspace(FPRIME, fprime_util)
if not (FPRIME / UT_BUILD_DIR).exists():
    t = time.time()
    p = run([ws.fprime_util, "generate", "--ut"], log=LOGS / "fprime_generate_ut.log", cwd=FPRIME, env=ws.env)
    print(f"fprime-util generate --ut: rc={p.returncode} in {time.time() - t:.0f}s")
FPRIME_BASE = ws.head()

graph, ingest_report = ingest_fprime(FPRIME)
ds = tr.build_dataset(graph)
store = InMemoryStore(graph)
print(
    f"graph: {graph.stats()}\ntraceability: {len(ds.req_ids)} requirements, {len(ds.candidates)} candidates"
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
configs_dir = OUT / "model_configs"
configs_dir.mkdir(exist_ok=True)
config_log = {}
if not DRY_RUN:
    from huggingface_hub import hf_hub_download

    for model, repos in CONFIG_REPOS.items():
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
        builds["llama.cpp"] = run(
            ["git", "-C", str(LLAMA_SERVER.parents[2]), "rev-parse", "HEAD"]
        ).stdout.strip()
    except Exception:
        builds["llama.cpp_error"] = traceback.format_exc()[-3000:]
if "vllm" in needs:
    try:
        VLLM = E.install_vllm(WORK, log=LOGS / "vllm_install.log")
        builds["vllm"] = run(
            [str(VLLM.parent / "python"), "-c", "import vllm; print(vllm.__version__)"]
        ).stdout.strip()
    except Exception:
        builds["vllm_error"] = traceback.format_exc()[-3000:]
save("builds.json", builds)
print(builds)


# %%
# ---------------------------------------------------------------- stages
corpus = load_corpus(FPRIME / "Svc")
profiles = make_profiles(corpus)
EVAL_TASKS = load_tasks()


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


def stage_serving(cfg, base_url, extra, res) -> None:
    run_blocking(run_level(base_url, "default", profiles["chat"], 1, 2, extra))  # warm-up
    for pname in PROFILES:
        levels = []
        for c in CONCURRENCY:
            with E.GpuPeakSampler() as sampler:
                summary, _ = run_blocking(
                    run_level(
                        base_url, "default", profiles[pname], c, max(MIN_REQUESTS_PER_LEVEL, 2 * c), extra
                    )
                )
            levels.append({**summary.as_dict(), "vram_peak_mib": sampler.peak_mib})
            print(cfg["key"], pname, c, round(summary.output_tps, 1), "tok/s")
        res["profiles"][pname] = levels
        save(f"serving/{cfg['key']}.json", res)


def stage_judge(cfg, base_url, extra) -> None:
    judge = tr.LlmJudge(base_url, "default", extra_body=extra)
    t = time.time()
    name = f"{best_hybrid_name}+llm-rerank@10"
    rerank = tr.llm_reranked(
        ds, rankers[best_hybrid_name], judge, top_n=10, max_workers=cfg.get("parallel", 4)
    )
    trace_results["methods"][name] = tr.evaluate(ds, rerank)
    trace_results["dataset"]["judge"] = {"config": cfg["key"], "seconds": round(time.time() - t, 1)}
    save("traceability.json", trace_results)


def stage_eval(cfg, generate) -> dict:
    partial = OUT / "eval" / f"{cfg['key']}.partial.jsonl"
    partial.parent.mkdir(parents=True, exist_ok=True)
    results = evalrunner.run_suite(
        EVAL_TASKS, generate, EVAL_SAMPLES, min(4, cfg.get("parallel", 4)), partial
    )
    meta = {"model": cfg["model"], "label": cfg["key"], "engine": cfg["engine"], "samples": EVAL_SAMPLES}
    report = evalrunner.build_report(results, EVAL_SAMPLES, meta)
    save(f"eval/{cfg['key']}.json", report)
    partial.unlink(missing_ok=True)
    print(evalrunner.markdown_table([report]))
    return report


def stage_agent(cfg, llm, req_ids=None) -> dict:
    ws.git("checkout", "-q", "--detach", FPRIME_BASE)
    out = OUT / "agent" / f"{cfg['key']}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    branch = f"oge-agent/{cfg['key']}"
    deps = AgentDeps(
        ws,
        None,
        llm,
        AgentConfig(max_attempts=AGENT_MAX_ATTEMPTS, mutants=AGENT_MUTANTS, model_label=cfg["key"]),
    )
    deadline = time.monotonic() + max(0.0, time_left() - 1800)

    async def go():
        async with KnowledgeClient(build_server(store)) as kb:
            deps.kb = kb
            ids = req_ids or await select_targets(kb, DEFAULT_MODULES)

            def progress(rec, done, total):
                print(f"[{done}/{total}] {rec['req_id']} {rec['status']} {rec['wall_seconds']}s")

            return await run_batch(deps, ids, out, branch, progress, deadline=deadline)

    records = run_blocking(go())
    summary = summarize(records)
    save(f"agent/{cfg['key']}.summary.json", summary)
    # the generated tests themselves, for review outside Kaggle (git am / git apply)
    patch = run(["git", "-C", str(FPRIME), "format-patch", "--stdout", f"{FPRIME_BASE}..{branch}"]).stdout
    (OUT / "agent" / f"{cfg['key']}.patch").write_text(patch)
    ws.git("checkout", "-q", "--detach", FPRIME_BASE)
    print(json.dumps({k: summary[k] for k in ("status", "verified_rate", "first_attempt_compile_rate")}))
    return summary


# %%
# ---------------------------------------------------------------- run every configuration
if DRY_RUN:  # oracle / scripted models exercise the eval and agent stages end to end without a GPU
    answers_file = Path(os.environ.get("BENCH_SCRIPTED", "tests/data/scripted_agent_answers.json"))
    answers = {k: v for k, v in json.loads(answers_file.read_text()).items() if not k.startswith("_")}
    dry = {"key": "dry-run", "model": "oracle", "engine": "none", "parallel": 4}
    stage_eval(dry, evalrunner.reference_generator)
    stage_agent(dry, ScriptedModel(answers), req_ids=list(answers))

for cfg in [] if DRY_RUN else CONFIGS:
    if time_left() < 3600:
        print("stopping: session budget")
        break
    if (cfg["engine"] == "llama.cpp" and LLAMA_SERVER is None) or (cfg["engine"] == "vllm" and VLLM is None):
        continue
    res = {"config": cfg, "profiles": {}, "stages": {}}
    srv = None
    try:
        t = time.time()
        srv, info = launch(cfg)
        res.update(info)
        srv.start()
        ok, why = srv.wait_ready(timeout_s=2400)
        res["load_s"] = round(time.time() - t, 1)
        if not ok:
            raise RuntimeError(
                f"server not ready: {why}\n{E.root_cause(srv.log_path.read_text(errors='replace'))}"
            )
        res["vram_idle_mib"] = E.gpu_memory_mib()
        if cfg["engine"] == "vllm":
            res["vllm_log"] = E.parse_vllm_log(srv.log_path.read_text(errors="replace"))
        extra = {"chat_template_kwargs": {"enable_thinking": False}} if cfg.get("disable_thinking") else None
        stages = cfg.get("stages", ["serving"])
        for stage in ["serving", "judge", "eval", "agent"]:
            if stage == "judge" and cfg["key"] != JUDGE_CONFIG:
                continue
            if stage != "judge" and stage not in stages:
                continue
            if stage == "agent" and time_left() < MIN_TIME_FOR_AGENT_S:
                res["stages"][stage] = "skipped: session budget"
                continue
            t = time.time()
            try:
                if stage == "serving":
                    stage_serving(cfg, srv.base_url, extra, res)
                elif stage == "judge":
                    stage_judge(cfg, srv.base_url, extra)
                elif stage == "eval":
                    client = evalrunner.ChatClient(srv.base_url, "default", extra_body=extra, max_tokens=4096)
                    stage_eval(cfg, client)
                else:
                    llm = ChatModel(srv.base_url, "default", extra_body=extra, max_tokens=4096)
                    stage_agent(cfg, llm.complete)
                res["stages"][stage] = f"done in {time.time() - t:.0f}s"
            except Exception:
                res["stages"][stage] = "error: " + traceback.format_exc()[-3000:]
            save(f"serving/{cfg['key']}.json", res)
    except Exception:
        res["error"] = traceback.format_exc()[-4000:]
    finally:
        if srv is not None:
            srv.stop()
        shutil.rmtree(WORK / "models" / cfg["key"], ignore_errors=True)
        if cfg["engine"] == "vllm":
            shutil.rmtree(WORK / "hf" / "hub", ignore_errors=True)
        save(f"serving/{cfg['key']}.json", res)

# %%
# ---------------------------------------------------------------- summary
lines = [
    "# Benchmark summary",
    "",
    f"repo commit `{repo_commit}` · GPUs {env['gpus']} · elapsed {(time.time() - T0) / 3600:.2f} h",
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
for f in sorted((OUT / "serving").glob("*.json")):
    r = json.loads(f.read_text())
    for lvl in r.get("profiles", {}).get("chat", []):
        lines.append(
            f"| {r['config']['key']} | {lvl['concurrency']} | {lvl['output_tps']:.1f} | "
            f"{(lvl['ttft_p50_s'] or 0):.2f} | {(lvl['tpot_p50_ms'] or 0):.1f} |"
        )
    if "error" in r:
        lines.append(f"| {r['config']['key']} | error | {r['error'].strip().splitlines()[-1][:80]} | | |")
eval_reports = [json.loads(f.read_text()) for f in sorted((OUT / "eval").glob("*.json"))]
if eval_reports:
    lines += [
        "",
        "## Model evaluation (embedded C, scored by execution)",
        "",
        evalrunner.markdown_table(eval_reports),
    ]
agent_rows = []
for f in sorted((OUT / "agent").glob("*.summary.json")):
    s = json.loads(f.read_text())
    mut = s.get("mutation", {})
    agent_rows.append(
        f"| {f.name.removesuffix('.summary.json')} | {s['targets']} | {s['status'].get('passed', 0)} | "
        f"{s['status'].get('not_testable', 0)} | {s['status'].get('suspected_defect', 0)} | "
        f"{(s['verified_rate'] or 0):.0%} | {(s['first_attempt_compile_rate'] or 0):.0%} | "
        f"{s['mean_attempts_when_verified'] or '–'} | {mut.get('killed', 0)}/{mut.get('valid_mutants', 0)} |"
    )
if agent_rows:
    lines += [
        "",
        "## Test-generation agent (F´ requirement gaps)",
        "",
        "| config | targets | verified | not testable | suspected defect | verified rate | 1st-try compile "
        "| attempts | mutants killed |",
        "|---|---|---|---|---|---|---|---|---|",
        *agent_rows,
    ]
(OUT / "summary.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
