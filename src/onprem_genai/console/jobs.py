"""Agent runs started from the console: a queue worked one run at a time, with live events for the browser.

Runs share one F´ working copy, so they are serialized. Each run starts from the base commit on its own
branch (``oge-console/run-<id>``), streams one event per agent step, stores every finished requirement as a
result for review, and can be stopped between requirements (the current one always finishes cleanly).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from onprem_genai.console.db import ConsoleDb
from onprem_genai.console.steps import step_event
from onprem_genai.knowledge.store import InMemoryStore


@dataclass
class RunRequest:
    req_ids: list[str]
    model_kind: str  # endpoint | replay
    attempts: int = 3
    mutants: int = 4


@dataclass
class Workspace:
    """Where the agent works: the F´ checkout, its tools, and the commit every run starts from."""

    fprime: Path | None
    fprime_util: str | None = None
    base_commit: str | None = None
    artifacts: Path = Path("artifacts/console")
    jobs: int | None = None
    problems: list[str] = field(default_factory=list)


def display_name(stem: str) -> str:
    """``qwen3-coder-30b-a3b`` → ``Qwen3-Coder-30B-A3B``: the model names used in the benchmark reports."""

    def word(part: str) -> str:
        if part[:1].isalpha() and part[-1:].isdigit():  # a name with a version: qwen3 -> Qwen3
            return part.capitalize()
        return part.upper() if any(ch.isdigit() for ch in part) else part.capitalize()

    return "-".join(word(p) for p in stem.split("-"))


def load_replay_answers(paths: list[Path]) -> dict[str, dict[str, Any]]:
    """Verified answers recorded in benchmark runs, by requirement (first file wins): the replay model.

    Only self-contained answers are kept: a repair answer may resend just the block it changed (the agent
    reuses the other block from the previous answer), and such an answer cannot be replayed on its own.
    """
    from onprem_genai.agent.patch import parse_answer  # noqa: PLC0415

    out: dict[str, dict[str, Any]] = {}
    for p in paths:
        label = display_name(p.stem.split("__")[0])
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            answer = rec.get("last_answer") or ""
            if rec.get("status") != "passed" or rec["req_id"] in out:
                continue
            blocks = parse_answer(answer)
            if blocks.tester_code.strip() and blocks.main_code.strip():
                out[rec["req_id"]] = {"answer": answer, "label": label}
    return out


class JobManager:
    def __init__(
        self,
        db: ConsoleDb,
        store: InMemoryStore,
        workspace: Workspace,
        replay: dict[str, dict[str, Any]],
    ) -> None:
        self.db, self.store, self.ws, self.replay = db, store, workspace, replay
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._seq: dict[int, int] = {}
        self._stop: set[int] = set()
        self._worker: asyncio.Task[None] | None = None
        self.current: int | None = None

    # -- lifecycle
    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._work())

    async def close(self) -> None:
        if self._worker:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker

    # -- API
    def submit(self, req: RunRequest, model_label: str, options: dict[str, Any]) -> int:
        run_id = self.db.create_run(
            req.model_kind,
            model_label,
            {**options, "attempts": req.attempts, "mutants": req.mutants},
            req.req_ids,
        )
        self._queue.put_nowait(run_id)
        self.publish(run_id, {"type": "run", "status": "queued"})
        return run_id

    def stop(self, run_id: int) -> str:
        run = self.db.run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["status"] == "queued":
            self.db.update_run(run_id, status="cancelled", finished_at=time.time())
            self.publish(run_id, {"type": "run", "status": "cancelled"})
            return "cancelled"
        if run["status"] == "running":
            self._stop.add(run_id)
            self.publish(run_id, {"type": "run", "status": "stopping"})
            return "stopping"
        return run["status"]

    def subscribe(self, run_id: int) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[run_id].add(q)
        return q

    def unsubscribe(self, run_id: int, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers[run_id].discard(q)

    def publish(self, run_id: int, payload: dict[str, Any]) -> None:
        if run_id not in self._seq:
            last = self.db.events(run_id)
            self._seq[run_id] = last[-1]["seq"] + 1 if last else 0
        seq = self._seq[run_id]
        self._seq[run_id] = seq + 1
        payload = {**payload, "ts": time.time()}
        self.db.add_event(run_id, seq, payload)
        for q in list(self._subscribers.get(run_id, ())):
            q.put_nowait({"seq": seq, **payload})

    # -- worker
    async def _work(self) -> None:
        while True:
            run_id = await self._queue.get()
            run = self.db.run(run_id)
            if run is None or run["status"] != "queued":
                continue
            self.current = run_id
            try:
                await self._execute(run)
            except Exception as exc:  # the worker must survive any failed run
                self.db.update_run(
                    run_id,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}"[:2000],
                    finished_at=time.time(),
                )
                self.publish(run_id, {"type": "run", "status": "failed", "error": str(exc)[:2000]})
            finally:
                self.current = None
                self._stop.discard(run_id)

    def _llm(self, run: dict[str, Any]) -> Any:
        from onprem_genai.agent.runner import ScriptedModel  # noqa: PLC0415
        from onprem_genai.llm import ChatModel  # noqa: PLC0415

        opts = run["options"]
        if run["model_kind"] == "replay":
            return ScriptedModel({r: [self.replay[r]["answer"]] for r in run["req_ids"] if r in self.replay})
        extra = opts.get("extra_body") or None
        client = ChatModel(
            opts["base_url"],
            opts.get("model") or "default",
            self.db.settings().get("llm_api_key") or None,  # never stored with the run
            float(opts.get("temperature", 0.2)),
            0.95,
            int(opts.get("max_tokens", 3072)),
            extra,
        )
        return client.complete

    async def _execute(self, run: dict[str, Any]) -> None:
        from onprem_genai.agent.fprime import FprimeWorkspace  # noqa: PLC0415
        from onprem_genai.agent.graph import AgentConfig, AgentDeps  # noqa: PLC0415
        from onprem_genai.agent.knowledge import KnowledgeClient  # noqa: PLC0415
        from onprem_genai.agent.runner import run_batch  # noqa: PLC0415
        from onprem_genai.mcp_server.server import build_server  # noqa: PLC0415

        run_id = run["id"]
        if self.ws.fprime is None:
            raise RuntimeError("no F´ workspace is configured; start the console with --fprime")
        self.db.update_run(run_id, status="running", started_at=time.time())
        self.publish(run_id, {"type": "run", "status": "running"})
        ws = FprimeWorkspace(self.ws.fprime, self.ws.fprime_util, self.ws.jobs)
        dirty = [f for f in await asyncio.to_thread(ws.changed_files) if "/test/ut/" in f]
        if dirty:
            raise RuntimeError(f"the F´ working copy has uncommitted test changes: {', '.join(dirty[:4])}")
        if self.ws.base_commit:
            await asyncio.to_thread(ws.git, "checkout", "-q", self.ws.base_commit)
        branch = f"oge-console/run-{run_id}"
        self.db.update_run(run_id, branch=branch)
        out = self.ws.artifacts / "runs" / f"{run_id}.jsonl"
        opts = run["options"]
        cfg = AgentConfig(
            max_attempts=int(opts.get("attempts", 3)),
            mutants=int(opts.get("mutants", 4)),
            model_label=run["model_label"],
        )
        llm = self._llm(run)

        def trace(req_id: str, node: str, update: dict[str, Any], state: dict[str, Any]) -> None:
            ev = step_event(req_id, node, update, state)
            if ev is not None:
                self.publish(run_id, ev)

        def progress(rec: dict[str, Any], done: int, total: int) -> None:
            label = run["model_label"]
            if run["model_kind"] == "replay" and rec["req_id"] in self.replay:
                label = f"{self.replay[rec['req_id']]['label']} (recorded)"
            result_id = self.db.add_result(rec, source="console", model_label=label, run_id=run_id)
            self.publish(
                run_id,
                {
                    "type": "result",
                    "req_id": rec["req_id"],
                    "status": rec["status"],
                    "reason": rec.get("reason", ""),
                    "attempts": rec.get("attempts"),
                    "wall_seconds": rec.get("wall_seconds"),
                    "result_id": result_id,
                    "done": done,
                    "total": total,
                },
            )

        async with KnowledgeClient(build_server(self.store)) as kb:
            records = await run_batch(
                AgentDeps(ws, kb, llm, cfg),
                run["req_ids"],
                out,
                branch,
                progress,
                trace=trace,
                should_stop=lambda: run_id in self._stop,
            )
        stopped = run_id in self._stop and len(records) < len(run["req_ids"])
        status = "cancelled" if stopped else "done"
        self.db.update_run(run_id, status=status, finished_at=time.time())
        self.publish(run_id, {"type": "run", "status": status})
