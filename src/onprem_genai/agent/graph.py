"""LangGraph state machine of the requirement-based test-generation agent.

    prepare ─► gather ─► generate ─► check ─► build ─► test ─► commit ─► evaluate ─► finish
                            ▲          │         │       │
                            └──────────┴─────────┴───────┘  repair loop (bounded by max_attempts)

The model only writes test code. Retrieval (MCP), patching, building, running, coverage and git are
deterministic nodes with fixed arguments, so the agent's authority is bounded: it can add unit tests to one
component's ``test/ut`` directory and nothing else. CI (Jenkins over MCP, ``agent.ci``) runs once per batch on
the run branch.
"""

# Node functions read keys written by earlier nodes; the graph edges guarantee they exist.
# pyright: reportTypedDictNotRequiredAccess=false

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from onprem_genai.agent import context as ctxmod
from onprem_genai.agent import mutation
from onprem_genai.agent.fprime import Component, FprimeWorkspace, UnsupportedComponentError
from onprem_genai.agent.knowledge import KnowledgeClient
from onprem_genai.agent.patch import PatchError, TestPatch, apply, build_patch, parse_answer
from onprem_genai.llm import Completion

SUSPECTED_DEFECT = re.compile(r"SUSPECTED[_ ]DEFECT\s*:\s*(.+?)(?:\n\s*\n|```|$)", re.DOTALL | re.IGNORECASE)
TERMINAL = {"passed", "not_testable", "suspected_defect", "failed", "unsupported", "env_error", "llm_error"}


@dataclass
class AgentConfig:
    max_attempts: int = 3
    context_chars: int = 36000
    test_repeat: int = 3  # run the new test several times (random seeds) to reject flaky tests
    mutants: int = 0  # fault-detection analysis after a successful commit (0 = off)
    model_label: str = "unknown-model"
    commit: bool = True


@dataclass
class Baseline:
    build_ok: bool
    tests_passed: bool
    tests: list[str]
    coverage: dict[str, float]
    build_seconds: float
    error: str = ""


@dataclass
class AgentDeps:
    ws: FprimeWorkspace
    kb: KnowledgeClient
    llm: Callable[[list[dict[str, str]]], Completion]
    cfg: AgentConfig = field(default_factory=AgentConfig)
    baselines: dict[str, Baseline] = field(default_factory=dict)


class AgentState(TypedDict, total=False):
    req_id: str
    module: str
    requirement: dict[str, Any]
    component: Component
    ctx: ctxmod.AgentContext
    messages: list[dict[str, str]]
    answer: str
    patch: TestPatch | None
    attempt: int
    feedback_kind: str | None
    history: list[dict[str, Any]]
    status: str
    reason: str
    metrics: dict[str, Any]
    commit: str | None
    diff: str


def _metric(state: AgentState, **updates: Any) -> dict[str, Any]:
    m = dict(state.get("metrics") or {})
    for k, v in updates.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and isinstance(m.get(k), (int, float)):
            m[k] = round(m[k] + v, 3)
        else:
            m[k] = v
    return m


def _record(state: AgentState, stage: str, detail: str = "", **extra: Any) -> list[dict[str, Any]]:
    entry = {"attempt": state.get("attempt", 0), "stage": stage, "detail": detail[:1500], **extra}
    return [*(state.get("history") or []), entry]


def build_graph(deps: AgentDeps):  # noqa: PLR0915  (returns a compiled LangGraph; nodes are closures)
    ws, kb, cfg = deps.ws, deps.kb, deps.cfg

    async def prepare(state: AgentState) -> dict[str, Any]:
        req = await kb.requirement(state["req_id"])
        if "error" in req:
            return {"status": "unsupported", "reason": req["error"]}
        module = (req.get("module") or "").removeprefix("module:")
        try:
            c = ws.component(module)
        except UnsupportedComponentError as exc:
            return {"status": "unsupported", "reason": str(exc), "module": module}
        if module not in deps.baselines:
            deps.baselines[module] = await asyncio.to_thread(_baseline, ws, c)
        base = deps.baselines[module]
        if not (base.build_ok and base.tests_passed):
            return {
                "status": "env_error",
                "reason": f"baseline unit tests broken: {base.error[:500]}",
                "module": module,
                "component": c,
            }
        return {
            "module": module,
            "requirement": req,
            "component": c,
            "attempt": 0,
            "history": [],
            "metrics": {
                "llm_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "llm_seconds": 0.0,
                "build_seconds": 0.0,
                "truncated": 0,
                "coverage_before": base.coverage,
            },
        }

    async def gather(state: AgentState) -> dict[str, Any]:
        c = state["component"]
        ctx = await ctxmod.build_context(ws, kb, c, state["req_id"])
        msgs = [
            {"role": "system", "content": ctxmod.SYSTEM_PROMPT},
            {"role": "user", "content": ctxmod.task_message(ctx, cfg.context_chars)},
        ]
        return {
            "ctx": ctx,
            "messages": msgs,
            "metrics": _metric(
                state,
                context_chars=len(msgs[1]["content"]),
                context_dropped=ctx.dropped,
                mcp_calls=len(kb.calls),
            ),
        }

    async def generate(state: AgentState) -> dict[str, Any]:
        try:
            comp = await asyncio.to_thread(deps.llm, state["messages"])
        except Exception as exc:
            return {"status": "llm_error", "reason": str(exc)[:500]}
        attempt = state.get("attempt", 0) + 1
        return {
            "answer": comp.text,
            "attempt": attempt,
            "messages": [*state["messages"], {"role": "assistant", "content": comp.text}],
            "metrics": _metric(
                state,
                llm_calls=1,
                prompt_tokens=comp.prompt_tokens or 0,
                completion_tokens=comp.completion_tokens or 0,
                llm_seconds=comp.latency_s,
                truncated=int(comp.finish_reason == "length"),
            ),
        }

    def _feedback(state: AgentState, kind: str, text: str, detail: str) -> dict[str, Any]:
        return {
            "feedback_kind": kind,
            "messages": [*state["messages"], {"role": "user", "content": text}],
            "history": _record({**state}, kind, detail),
        }

    async def check(state: AgentState) -> dict[str, Any]:
        text = state["answer"]
        if m := SUSPECTED_DEFECT.search(text):
            return {
                "status": "suspected_defect",
                "reason": " ".join(m.group(1).split())[:1500],
                "history": _record(state, "suspected_defect"),
            }
        ws.restore(
            state["component"].test_files
        )  # validate against the committed files, not the last attempt
        answer = parse_answer(text)
        if answer.not_testable:
            return {
                "status": "not_testable",
                "reason": answer.not_testable[:1000],
                "history": _record(state, "not_testable", answer.not_testable),
            }
        try:
            patch = build_patch(answer, state["component"], state["req_id"])
        except PatchError as exc:
            return {
                "patch": None,
                **_feedback(state, "policy", ctxmod.REPAIR_POLICY.format(error=exc), str(exc)),
            }
        return {"patch": patch, "feedback_kind": None}

    async def build(state: AgentState) -> dict[str, Any]:
        c, patch = state["component"], state["patch"]
        assert patch is not None
        ws.restore(c.test_files)
        apply(c, patch, state["req_id"])
        res = await asyncio.to_thread(ws.build_ut, c)
        metrics = _metric(state, build_seconds=res.seconds)
        if state["attempt"] == 1:
            metrics["first_attempt_compiled"] = res.ok
        if res.ok:
            metrics["compiled"] = True
            return {"metrics": metrics, "feedback_kind": None}
        hints = await ctxmod.repair_hints(res.errors, state["ctx"], kb, c)
        out = _feedback(
            state, "build", ctxmod.REPAIR_BUILD.format(errors=res.errors, hints=hints), res.errors
        )
        return {**out, "metrics": metrics}

    async def test(state: AgentState) -> dict[str, Any]:
        c, patch = state["component"], state["patch"]
        assert patch is not None
        ws.reset_coverage(c)
        new = await asyncio.to_thread(ws.run_ut, c, patch.gtest_filter, cfg.test_repeat)
        new_cov = ws.coverage(c)
        if not new.passed:
            failures = "\n".join(new.failures) or new.output_tail
            return _feedback(state, "test", ctxmod.REPAIR_TEST.format(failures=failures[:3000]), failures)
        ws.reset_coverage(c)
        full = await asyncio.to_thread(ws.run_ut, c)
        base = deps.baselines[state["module"]]
        if not full.passed:
            others = [f for f in full.failures if not f.startswith(tuple(patch.test_names))]
            failures = "\n".join(others or full.failures) or full.output_tail
            return _feedback(
                state, "regression", ctxmod.REPAIR_REGRESSION.format(failures=failures[:3000]), failures
            )
        cov = ws.coverage(c)
        return {
            "diff": ws.diff(c.test_files),
            "history": _record(state, "passed", ", ".join(patch.test_names)),
            "metrics": _metric(
                state,
                new_test_coverage=new_cov,
                coverage_after=cov,
                coverage_delta=round(cov["line_coverage"] - base.coverage["line_coverage"], 4),
                tests_total=full.tests,
                test_names=patch.test_names,
            ),
        }

    async def commit(state: AgentState) -> dict[str, Any]:
        c = state["component"]
        sha = None
        if cfg.commit:
            sha = ws.commit(
                c.test_files,
                _commit_message(state, cfg),
                f"oge-agent ({cfg.model_label}) <oge-agent@localhost>",
            )
        base = deps.baselines[state["module"]]
        metrics = state.get("metrics") or {}
        deps.baselines[state["module"]] = Baseline(
            True,
            True,
            base.tests + list(metrics.get("test_names", [])),
            metrics.get("coverage_after", base.coverage),
            base.build_seconds,
        )
        return {"status": "passed", "commit": sha}

    async def evaluate(state: AgentState) -> dict[str, Any]:
        if cfg.mutants <= 0 or state.get("patch") is None:
            return {}
        patch = state["patch"]
        assert patch is not None
        rep = await asyncio.to_thread(
            mutation.analyse, ws, state["component"], patch.gtest_filter, cfg.mutants, state["req_id"]
        )
        return {"metrics": _metric(state, mutation=rep.as_dict())}

    async def give_up(state: AgentState) -> dict[str, Any]:
        return {
            "status": "failed",
            "reason": f"no passing test after {state.get('attempt', 0)} attempt(s); "
            f"last failure: {state.get('feedback_kind')}",
        }

    async def finish(state: AgentState) -> dict[str, Any]:
        c = state.get("component")
        if c is not None and state.get("status") != "passed":
            ws.restore(c.test_files)
        return {}

    def after_prepare(state: AgentState) -> str:
        return "finish" if state.get("status") in TERMINAL else "gather"

    def after_generate(state: AgentState) -> str:
        return "finish" if state.get("status") in TERMINAL else "check"

    def retry_or(next_node: str) -> Callable[[AgentState], str]:
        def route(state: AgentState) -> str:
            if state.get("status") in TERMINAL:
                return "finish"
            if state.get("feedback_kind"):
                return "generate" if state.get("attempt", 0) < cfg.max_attempts else "give_up"
            return next_node

        return route

    g = StateGraph(AgentState)
    for name, fn in [
        ("prepare", prepare),
        ("gather", gather),
        ("generate", generate),
        ("check", check),
        ("build", build),
        ("test", test),
        ("commit", commit),
        ("evaluate", evaluate),
        ("give_up", give_up),
        ("finish", finish),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "prepare")
    g.add_conditional_edges("prepare", after_prepare, ["gather", "finish"])
    g.add_edge("gather", "generate")
    g.add_conditional_edges("generate", after_generate, ["check", "finish"])
    g.add_conditional_edges("check", retry_or("build"), ["build", "generate", "give_up", "finish"])
    g.add_conditional_edges("build", retry_or("test"), ["test", "generate", "give_up", "finish"])
    g.add_conditional_edges("test", retry_or("commit"), ["commit", "generate", "give_up", "finish"])
    g.add_edge("commit", "evaluate")
    g.add_edge("evaluate", "finish")
    g.add_edge("give_up", "finish")
    g.add_edge("finish", END)
    return g.compile()


def _baseline(ws: FprimeWorkspace, c: Component) -> Baseline:
    ws.restore(c.test_files)
    t0 = time.perf_counter()
    b = ws.build_ut(c)
    if not b.ok:
        return Baseline(False, False, [], {}, b.seconds, b.errors)
    ws.reset_coverage(c)
    run = ws.run_ut(c)
    return Baseline(
        True,
        run.passed,
        ws.list_tests(c),
        ws.coverage(c),
        round(time.perf_counter() - t0, 2),
        "\n".join(run.failures),
    )


def _commit_message(state: AgentState, cfg: AgentConfig) -> str:
    c = state["component"]
    req = state.get("requirement") or {}
    names = ", ".join((state.get("metrics") or {}).get("test_names", []))
    text = " ".join(str(req.get("text", "")).split())
    return (
        f"test({c.name}): verify {state['req_id']} with a requirement-tagged unit test\n\n"
        f"Requirement {state['req_id']}: {text}\n"
        f"New test(s): {names}\n\n"
        f"AI-Assisted: yes. Test code generated by {cfg.model_label} through the onprem-genai-embedded agent "
        f"({state.get('attempt', 0)} attempt(s)); built and run automatically. Requires human review "
        f"before merge.\n"
    )
