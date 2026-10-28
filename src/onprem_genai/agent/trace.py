"""One readable line per agent step, from the LangGraph node updates (``oge agent run --trace``)."""

from __future__ import annotations

from typing import Any


def _first_line(text: str, limit: int = 110) -> str:
    for raw in str(text).splitlines():
        if raw.strip():
            line = " ".join(raw.split())
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def describe(node: str, update: dict[str, Any], state: dict[str, Any]) -> str | None:
    """Text for one node's update (``state`` already includes it); None for steps not worth a line."""
    metrics = state.get("metrics") or {}
    kind = update.get("feedback_kind")
    if node == "prepare":
        if update.get("status"):
            return f"{update['status']}: {_first_line(update.get('reason', ''))}"
        cov = (metrics.get("coverage_before") or {}).get("line_coverage")
        cov_txt = f", line coverage {cov:.0%}" if isinstance(cov, (int, float)) else ""
        return f"{state.get('module')}: baseline unit tests build and pass{cov_txt}"
    if node == "gather":
        ctx = state.get("ctx")
        titles = [s.title.split(" (")[0] for s in getattr(ctx, "sections", [])][:6]
        calls, chars = metrics.get("mcp_calls", 0), metrics.get("context_chars", 0)
        return f"{calls} MCP calls → {chars:,} chars of context: " + ", ".join(titles)
    if node == "generate":
        if update.get("status"):
            return f"LLM error: {_first_line(update.get('reason', ''))}"
        lines = len(str(update.get("answer", "")).splitlines())
        return f"attempt {update.get('attempt')}: model answered ({lines} lines)"
    if node == "check":
        if update.get("status"):
            return f"{update['status']}: {_first_line(update.get('reason', ''))}"
        if kind:
            return f"policy rejected → repair: {_first_line(state['history'][-1]['detail'])}"
        patch = update.get("patch")
        names = ", ".join(patch.test_names) if patch else ""
        return f"policy OK: new test {names}, only test files touched"
    if node == "build":
        if kind:
            return f"build failed → repair: {_first_line(state['history'][-1]['detail'])}"
        return f"fprime-util build --ut: compiled in {metrics.get('build_seconds', 0):.1f} s"
    if node == "test":
        if kind:
            return f"{kind} failed → repair: {_first_line(state['history'][-1]['detail'])}"
        cov = (metrics.get("new_test_coverage") or {}).get("line_coverage")
        cov_txt = f"; it alone covers {cov:.0%} of the component" if isinstance(cov, (int, float)) else ""
        return f"new test passes 3 runs, full suite passes ({metrics.get('tests_total', '?')} tests){cov_txt}"
    if node == "commit":
        sha = (update.get("commit") or "")[:10]
        return f"committed {sha} (review branch, AI-use disclosure in the message)" if sha else "verified"
    if node == "evaluate":
        mut = metrics.get("mutation") or {}
        if not mut.get("valid"):
            return None
        ops = ", ".join(sorted({m["operator"] for m in mut.get("mutants", [])}))
        return f"fault detection: {mut['killed']}/{mut['valid']} mutants of the code it runs killed ({ops})"
    if node == "give_up":
        return f"failed: {_first_line(update.get('reason', ''))}"
    return None
