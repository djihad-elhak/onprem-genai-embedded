"""Batch runs of the agent: one git branch per run, one commit per verified requirement.

Results are appended to a JSONL file as each requirement finishes, so an interrupted run resumes where it
stopped (the run branch keeps the commits already made).
"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from onprem_genai.agent.graph import AgentDeps, build_graph
from onprem_genai.llm import Completion

# Components of the default benchmark: communication and parameter services with standard Tester/TestMain
# harnesses and no requirement-ID mismatches in the traceability audit (see docs/AGENT.md).
DEFAULT_MODULES = ["Svc/ComStub", "Svc/ComRetry", "Svc/PrmDb", "Svc/FprimeRouter"]


async def select_targets(
    kb: Any, modules: list[str] | None = None, req_ids: list[str] | None = None
) -> list[str]:
    if req_ids:
        return list(dict.fromkeys(req_ids))
    out: list[str] = []
    for m in modules or DEFAULT_MODULES:
        gaps = await kb.gaps(m)
        out += sorted(g["req_id"] for g in gaps)
    return out


def _record(req_id: str, state: dict[str, Any], wall_s: float) -> dict[str, Any]:
    metrics = dict(state.get("metrics") or {})
    return {
        "req_id": req_id,
        "module": state.get("module"),
        "status": state.get("status", "error"),
        "reason": state.get("reason", ""),
        "attempts": state.get("attempt", 0),
        "commit": state.get("commit"),
        "wall_seconds": round(wall_s, 2),
        "metrics": metrics,
        "history": state.get("history", []),
        "diff": state.get("diff", ""),
        "last_answer": state.get("answer", "")[-6000:],
    }


async def run_batch(
    deps: AgentDeps,
    req_ids: list[str],
    out: Path,
    branch: str,
    progress: Callable[[dict[str, Any], int, int], None] | None = None,
    deadline: float | None = None,
    trace: Callable[[str, str, dict[str, Any], dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Run the agent on each requirement; with ``deadline`` (time.monotonic), start no new one after it.

    ``trace(req_id, node, update, state)`` is called after every graph step (streamed node updates);
    ``should_stop()`` is checked before each requirement (a stop request finishes the current one first).
    """
    ws = deps.ws
    done: dict[str, dict[str, Any]] = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["req_id"]] = rec
    dirty = [f for f in ws.changed_files() if "/test/ut/" in f]
    if dirty:
        raise RuntimeError(f"uncommitted changes in unit-test files, refusing to run: {dirty[:5]}")
    existing = ws.git("branch", "--list", branch, check=False)
    if existing and done:
        ws.git("checkout", "-q", branch)
    else:
        ws.start_branch(branch)
    out.parent.mkdir(parents=True, exist_ok=True)
    graph = build_graph(deps)
    todo = [r for r in req_ids if r not in done]
    for req_id in todo:
        if (deadline is not None and time.monotonic() > deadline) or (should_stop and should_stop()):
            break
        t0 = time.perf_counter()
        try:
            if trace is None:
                state = await graph.ainvoke({"req_id": req_id}, {"recursion_limit": 100})
            else:
                state = {"req_id": req_id}
                config: Any = {"recursion_limit": 100}
                async for chunk in graph.astream({"req_id": req_id}, config, stream_mode="updates"):
                    for node, update in chunk.items():
                        state.update(update or {})  # no reducers: an update replaces its keys
                        trace(req_id, node, update or {}, state)
        except Exception as exc:
            state = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"[:1000]}
            leftovers = [f for f in ws.changed_files() if "/test/ut/" in f]
            if leftovers:  # never leave a half-applied edit behind
                ws.git("checkout", "-q", "HEAD", "--", *leftovers, check=False)
        rec = _record(req_id, dict(state), time.perf_counter() - t0)
        done[req_id] = rec
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        if progress:
            progress(rec, len(done), len(req_ids))
    return [done[r] for r in req_ids if r in done]


async def verify_with_ci(
    ci: Any, records: list[dict[str, Any]], branch: str, out: Path
) -> dict[str, Any] | None:
    """Run the CI pipeline once on the run branch for every component that received a verified test."""
    modules = sorted({r["module"] for r in records if r["status"] == "passed" and r.get("commit")})
    if not modules:
        return None
    result = (await ci.run(branch, modules)).as_dict()
    out.with_suffix(".ci.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


# ------------------------------------------------------------------------------------------- summary
# Primary cause of a failed attempt: first matching rule, in this order (from the run-2 failure analysis).
FAILURE_CAUSES: list[tuple[str, tuple[str, ...], str]] = [
    (
        "dispatch call on the wrong object or a passive component",
        ("build",),
        r"no member named [‘'`](?:doDispatch|dispatchAll|dispatchOne|component)[’'`]",
    ),
    ("namespace-qualified method definition", ("build",), r"invalid use of [‘'`]::[’'`]"),
    ("-Werror: C-style cast or deprecated API", ("build",), r"old-style-cast|deprecated"),
    ("other compile error", ("build",), r""),
    ("answer missing a block", ("policy",), r"missing the ```cpp"),
    ("reused an existing method or test name", ("policy",), r"already (?:defines|exist)"),
    ("other policy rejection", ("policy",), r""),
    (
        "F´ assertion in the component (precondition broken)",
        ("test", "regression"),
        r"Assertion `false' failed|Assert: \"",
    ),
    ("wrong expected value", ("test", "regression"), r""),
]


def failure_causes(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Failed attempts by primary cause: ``{cause: {"attempts": n, "requirements": k}}``."""
    attempts: Counter[str] = Counter()
    reqs: dict[str, set[str]] = defaultdict(set)
    for r in records:
        for h in r.get("history", []):
            stage, detail = h.get("stage"), str(h.get("detail", ""))
            for cause, stages, pattern in FAILURE_CAUSES:
                if stage in stages and re.search(pattern, detail):
                    attempts[cause] += 1
                    reqs[cause].add(r["req_id"])
                    break
    return {c: {"attempts": n, "requirements": len(reqs[c])} for c, n in attempts.most_common()}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    status = Counter(r["status"] for r in records)
    attempted = [r for r in records if r["status"] not in ("unsupported", "env_error")]
    passed = [r for r in records if r["status"] == "passed"]
    first = [
        r["metrics"].get("first_attempt_compiled")
        for r in attempted
        if "first_attempt_compiled" in r["metrics"]
    ]
    compiled = [bool(r["metrics"].get("compiled")) for r in attempted if r["metrics"].get("llm_calls")]
    muts = [r["metrics"]["mutation"] for r in passed if r["metrics"].get("mutation", {}).get("valid")]
    per_module: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"targets": 0, "passed": 0, "coverage_delta": 0.0}
    )
    for r in records:
        pm = per_module[r.get("module") or "?"]
        pm["targets"] += 1
        if r["status"] == "passed":
            pm["passed"] += 1
            pm["coverage_delta"] = round(pm["coverage_delta"] + r["metrics"].get("coverage_delta", 0.0), 4)

    def mean(xs: list[float]) -> float | None:
        return round(statistics.fmean(xs), 4) if xs else None

    return {
        "targets": n,
        "status": dict(status),
        "verified_rate": round(len(passed) / len(attempted), 4) if attempted else None,
        "first_attempt_compile_rate": mean([float(x) for x in first]),
        "compile_rate": mean([float(x) for x in compiled]),
        "mean_attempts_when_verified": mean([float(r["attempts"]) for r in passed]),
        "median_wall_seconds": statistics.median([r["wall_seconds"] for r in attempted])
        if attempted
        else None,
        "llm_calls": sum(r["metrics"].get("llm_calls", 0) for r in records),
        "completion_tokens": sum(r["metrics"].get("completion_tokens", 0) for r in records),
        "mutation": {
            "tests_analysed": len(muts),
            "valid_mutants": sum(m["valid"] for m in muts),
            "killed": sum(m["killed"] for m in muts),
            "mean_score": mean([m["score"] for m in muts if m.get("score") is not None]),
        },
        "per_module": dict(per_module),
        "gaps_closed": len(passed),
        "failure_causes": failure_causes(records),
    }


def review_sheet(records: list[dict[str, Any]], title: str, ci: dict[str, Any] | None = None) -> str:
    """Markdown for the human review of every generated test (relevance cannot be measured automatically)."""
    lines = [f"# Review sheet — {title}", ""]
    if ci:
        tests = ci.get("tests") or {}
        passed, total = tests.get("passCount", "?"), tests.get("totalCount", "?")
        lines += [
            f"CI: Jenkins `{ci['job']}` #{ci.get('build_number')} on `{ci['branch']}` → "
            f"**{ci.get('result')}** ({passed}/{total} tests passed)",
            "",
        ]
    lines += [
        "For each verified requirement: does the test exercise the behaviour the requirement states and "
        "check its outcome? Verdict: **relevant** / **partial** / **not relevant**.",
        "",
    ]
    for r in records:
        lines.append(f"## {r['req_id']} — {r['status']}")
        lines.append("")
        if r["status"] == "passed":
            mut = r["metrics"].get("mutation") or {}
            score = "–" if not mut.get("valid") else f"{mut['killed']}/{mut['valid']} mutants killed"
            lines += [
                f"- tests: {', '.join(r['metrics'].get('test_names', []))}; attempts: {r['attempts']}; "
                f"fault detection: {score}; commit `{(r.get('commit') or '')[:10]}`",
                "- verdict: ",
                "",
                "```diff",
                r.get("diff", "").strip(),
                "```",
                "",
            ]
        else:
            lines += [f"- reason: {r.get('reason', '')}", ""]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------- scripted model
@dataclass
class ScriptedModel:
    """Replays prepared answers per requirement (tests and demos without a GPU)."""

    answers: dict[str, list[str]]

    def __post_init__(self) -> None:
        self._served: Counter[str] = Counter()

    def __call__(self, messages: list[dict[str, str]]) -> Completion:
        task = next(m["content"] for m in messages if m["role"] == "user")
        m = re.search(r"verifies requirement (\S+?)\.", task)
        req = m.group(1) if m else ""
        script = self.answers.get(req) or ["NOT_TESTABLE: no scripted answer"]
        i = min(self._served[req], len(script) - 1)
        self._served[req] += 1
        return Completion(
            text=script[i],
            latency_s=0.0,
            prompt_tokens=len(task) // 4,
            completion_tokens=200,
            finish_reason="stop",
        )
