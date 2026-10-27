"""Run the evaluation suite against any OpenAI-compatible endpoint and aggregate the scores.

Each (task, sample) job is: build the prompt -> one chat completion -> extract the code -> score it (compile,
run hidden tests, sanitizers, coverage, mutants, complexity, documentation). Jobs run concurrently; finished
jobs are appended to a ``.partial.jsonl`` file so a long run (e.g. a Kaggle session) can resume after a crash.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from onprem_genai.evalsuite import prompts
from onprem_genai.evalsuite.scoring import reference_output, score
from onprem_genai.evalsuite.tasks import Category, Task, tasks_dir


@dataclass
class Completion:
    text: str
    latency_s: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


Generator = Callable[[Task, list[dict[str, str]]], Completion]


class ChatClient:
    """Minimal OpenAI-compatible chat-completions client (llama.cpp server, vLLM, SGLang, TGI, ...)."""

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

    def __call__(self, task: Task, messages: list[dict[str, str]]) -> Completion:
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
        raise RuntimeError(f"chat completion failed for {task.id}: {last}") from last


def reference_generator(task: Task, messages: list[dict[str, str]]) -> Completion:
    """Oracle 'model' answering with the reference solution: proves the harness end to end (expect 100%)."""
    del messages
    return Completion(text=f"Here is the file.\n```c\n{reference_output(task)}```\n")


# ------------------------------------------------------------------------------------------- run
@dataclass
class JobResult:
    task: str
    category: str
    sample: int
    passed: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    latency_s: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    error: str | None = None
    code: str = ""
    logs: dict[str, str] = field(default_factory=dict)


def suite_fingerprint(root: Path | None = None) -> str:
    """Hash of the task files and prompt templates: results are comparable only with equal fingerprints."""
    h = hashlib.sha256()
    base = root or tasks_dir()
    for p in sorted(base.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(base).as_posix().encode())
            h.update(p.read_bytes())
    h.update(prompts.SYSTEM_PROMPT.encode())
    h.update(prompts.TEST_FRAMEWORK_DOC.encode())
    return h.hexdigest()[:12]


def run_job(task: Task, sample: int, generate: Generator) -> JobResult:
    messages = prompts.build_messages(task)
    try:
        comp = generate(task, messages)
    except Exception as exc:  # a failed request is a failed sample, never a crashed run
        return JobResult(task.id, task.category.value, sample, False, error=str(exc)[:500])
    code = prompts.extract_code(comp.text)
    s = score(task, code)
    return JobResult(
        task.id,
        task.category.value,
        sample,
        s.passed,
        s.metrics,
        round(comp.latency_s, 3),
        comp.prompt_tokens,
        comp.completion_tokens,
        comp.finish_reason,
        None,
        code,
        {k: v[-1500:] for k, v in s.logs.items() if v},
    )


def run_suite(
    tasks: list[Task],
    generate: Generator,
    samples: int = 1,
    concurrency: int = 4,
    partial_path: Path | None = None,
    progress: Callable[[JobResult, int, int], None] | None = None,
) -> list[JobResult]:
    """Run every (task, sample) job; resumes from ``partial_path`` when it already holds finished jobs."""
    done: dict[tuple[str, int], JobResult] = {}
    if partial_path and partial_path.exists():
        for line in partial_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = JobResult(**json.loads(line))
                done[(r.task, r.sample)] = r
    todo = [(t, k) for t in tasks for k in range(samples) if (t.id, k) not in done]
    total = len(tasks) * samples
    if partial_path:
        partial_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(run_job, t, k, generate) for t, k in todo]
        for fut in as_completed(futures):
            r = fut.result()
            done[(r.task, r.sample)] = r
            if partial_path:
                with partial_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(asdict(r)) + "\n")
            if progress:
                progress(r, len(done), total)
    order = {t.id: i for i, t in enumerate(tasks)}
    return sorted(
        (r for r in done.values() if r.task in order and r.sample < samples),
        key=lambda r: (order[r.task], r.sample),
    )


# ------------------------------------------------------------------------------------------- aggregation
def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator (Chen et al., 2021): probability that at least one of k samples passes."""
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def _mean(values: list[float]) -> float | None:
    return round(float(np.mean(values)), 4) if values else None


def _ci(per_task: list[float], bootstrap: int = 2000, seed: int = 0) -> list[float] | None:
    if len(per_task) < 2:
        return None
    rng = np.random.default_rng(seed)
    arr = np.asarray(per_task, dtype=np.float64)
    boots = arr[rng.integers(0, len(arr), (bootstrap, len(arr)))].mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


_CATEGORY_METRICS: dict[str, list[tuple[str, Callable[[dict[str, Any]], float | None]]]] = {
    "generate": [
        ("compile_rate", lambda m: float(m.get("compiled", False))),
        ("tests_pass_rate", lambda m: float(m.get("tests_passed", False))),
        ("sanitizer_clean_rate", lambda m: float(m.get("sanitizer_clean", False))),
        ("mean_warnings", lambda m: float(m.get("warnings", 0)) if m.get("compiled") else None),
        ("policy_violation_rate", lambda m: float(bool(m.get("violations")))),
    ],
    "testgen": [
        ("valid_rate", lambda m: float(m.get("tests_pass_on_reference", False))),
        ("line_coverage", lambda m: float(m.get("line_coverage", 0.0))),
        ("branch_coverage", lambda m: float(m.get("branch_coverage", 0.0))),
        ("mutation_score", lambda m: float(m.get("mutation_score", 0.0))),
    ],
    "refactor": [
        ("behaviour_preserved_rate", lambda m: float(m.get("tests_passed", False))),
        (
            "ccn_max_reduction",
            lambda m: (
                1 - m["ccn_max_after"] / m["ccn_max_before"]
                if m.get("tests_passed") and m.get("ccn_max_before")
                else None
            ),
        ),
        ("goto_or_policy_violation_rate", lambda m: float(bool(m.get("violations")))),
    ],
    "document": [
        ("code_unchanged_rate", lambda m: float(m.get("code_unchanged", False))),
        ("doc_completeness", lambda m: float(m.get("doc_completeness", 0.0))),
    ],
}


def summarize(results: list[JobResult], samples: int) -> dict[str, Any]:
    by_cat: dict[str, dict[str, list[JobResult]]] = defaultdict(lambda: defaultdict(list))
    for r in results:
        by_cat[r.category][r.task].append(r)
    cats: dict[str, Any] = {}
    for cat in [c.value for c in Category]:
        tasks = by_cat.get(cat)
        if not tasks:
            continue
        per_task_p1 = [pass_at_k(len(rs), sum(r.passed for r in rs), 1) for rs in tasks.values()]
        entry: dict[str, Any] = {
            "tasks": len(tasks),
            "pass@1": round(float(np.mean(per_task_p1)), 4),
            "pass@1_ci95": _ci(per_task_p1),
        }
        if samples > 1:
            entry[f"pass@{samples}"] = round(
                float(
                    np.mean([pass_at_k(len(rs), sum(r.passed for r in rs), samples) for rs in tasks.values()])
                ),
                4,
            )
        all_runs = [r for rs in tasks.values() for r in rs]
        for name, fn in _CATEGORY_METRICS[cat]:
            vals = [v for r in all_runs if not r.error and (v := fn(r.metrics)) is not None]
            entry[name] = _mean(vals)
        entry["request_errors"] = sum(r.error is not None for r in all_runs)
        cats[cat] = entry
    lat = [r.latency_s for r in results if not r.error and r.latency_s]
    toks = [r.completion_tokens for r in results if r.completion_tokens]
    return {
        "categories": cats,
        "overall_pass@1": round(float(np.mean([c["pass@1"] for c in cats.values()])), 4) if cats else None,
        "jobs": len(results),
        "request_errors": sum(r.error is not None for r in results),
        "truncated": sum(r.finish_reason == "length" for r in results),
        "mean_latency_s": _mean(lat),
        "mean_completion_tokens": _mean([float(t) for t in toks]),
    }


def build_report(
    results: list[JobResult], samples: int, meta: dict[str, Any], include_code: bool = True
) -> dict[str, Any]:
    rows = [asdict(r) for r in results]
    if not include_code:
        for row in rows:
            row.pop("code", None)
    return {
        "meta": {
            **meta,
            "suite": suite_fingerprint(),
            "samples": samples,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "summary": summarize(results, samples),
        "results": rows,
    }


# ------------------------------------------------------------------------------------------- markdown
def markdown_table(reports: list[dict[str, Any]]) -> str:
    """Side-by-side comparison of several run reports (one row per model)."""
    head = (
        "| Model | Generate pass@1 | Test-gen pass@1 (mutation score) | Refactor pass@1 (CCN↓) | "
        "Document pass@1 | Overall | Latency / task |\n|---|---|---|---|---|---|---|"
    )
    suites = {r["meta"].get("suite") for r in reports}
    lines = [head]

    def pct(v: float | None) -> str:
        return "–" if v is None else f"{100 * v:.0f}%"

    for rep in reports:
        c, s = rep["summary"]["categories"], rep["summary"]
        g, t, f, d = (c.get(k, {}) for k in ("generate", "testgen", "refactor", "document"))
        lat = s.get("mean_latency_s")
        lines.append(
            f"| {rep['meta'].get('label') or rep['meta'].get('model')} | {pct(g.get('pass@1'))} | "
            f"{pct(t.get('pass@1'))} ({pct(t.get('mutation_score'))}) | "
            f"{pct(f.get('pass@1'))} ({pct(f.get('ccn_max_reduction'))}) | {pct(d.get('pass@1'))} | "
            f"{pct(s.get('overall_pass@1'))} | {'–' if lat is None else f'{lat:.0f} s'} |"
        )
    if len(suites) > 1:
        lines.append(f"\n> Warning: reports come from different suite versions {sorted(map(str, suites))}.")
    return "\n".join(lines) + "\n"
