"""Turn the agent's graph updates into the step events the console shows (and stores for later viewing)."""

from __future__ import annotations

from typing import Any

from onprem_genai.agent.trace import describe

_FAILED_WORDS = ("failed", "rejected", "error")


def step_event(
    req_id: str, node: str, update: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    """One event per meaningful step: a summary line plus the material an engineer wants to inspect."""
    line = describe(node, update, state)
    if line is None:
        return None
    status = update.get("status")
    ok = not any(w in line for w in _FAILED_WORDS) and status in (None, "passed")
    ev: dict[str, Any] = {"type": "step", "req_id": req_id, "node": node, "ok": ok, "line": line}
    metrics = state.get("metrics") or {}
    history = state.get("history") or []
    if node == "prepare":
        req = state.get("requirement") or {}
        ev["requirement"] = {
            "text": " ".join(str(req.get("text", "")).split()),
            "module": state.get("module"),
        }
        ev["coverage_before"] = (metrics.get("coverage_before") or {}).get("line_coverage")
    elif node == "gather":
        ctx = state.get("ctx")
        ev["sections"] = [s.title for s in getattr(ctx, "sections", [])]
        ev["context_chars"] = metrics.get("context_chars")
        ev["dropped"] = metrics.get("context_dropped") or []
    elif node == "generate":
        ev["attempt"] = update.get("attempt")
        ev["answer"] = str(update.get("answer", ""))[-8000:]
    elif node in ("check", "build", "test") and update.get("feedback_kind") and history:
        ev["detail"] = history[-1].get("detail", "")
        ev["attempt"] = history[-1].get("attempt")
    elif node == "build":
        ev["build_seconds"] = metrics.get("build_seconds")
    elif node == "test":
        ev["tests_total"] = metrics.get("tests_total")
        ev["new_test_coverage"] = (metrics.get("new_test_coverage") or {}).get("line_coverage")
    elif node == "commit":
        ev["commit"] = update.get("commit")
        ev["diff"] = str(state.get("diff", ""))[:20000]
    elif node == "evaluate":
        ev["mutation"] = metrics.get("mutation")
    elif node == "give_up":
        ev["reason"] = update.get("reason", "")
    return ev
