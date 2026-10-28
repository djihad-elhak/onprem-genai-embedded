"""HTTP API and static front end of the engineering console (Starlette, no internet access needed).

All state lives in the SQLite file; the knowledge graph is loaded once at start. Agent runs stream their steps
with server-sent events. The API key of the model server is write-only: it is never sent back to a browser.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import subprocess
import time
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from onprem_genai import __version__
from onprem_genai.console.catalog import STATES, Catalog, overlay_state
from onprem_genai.console.db import VERDICTS, ConsoleDb
from onprem_genai.console.jobs import JobManager, RunRequest, Workspace, display_name, load_replay_answers
from onprem_genai.knowledge.model import Graph
from onprem_genai.knowledge.store import InMemoryStore

STATIC = Path(__file__).with_name("static")
DEFAULT_LLM = {
    "base_url": "",
    "model": "default",
    "label": "",
    "temperature": 0.2,
    "max_tokens": 3072,
    "extra_body": None,
}
SEARCH_KINDS = {"Function", "TestCase", "Requirement", "DocChunk", "Class"}


@dataclass
class ConsoleConfig:
    graph: Path
    db: Path
    fprime: Path | None = None
    fprime_util: str | None = None
    artifacts: Path = Path("artifacts/console")
    imports: list[tuple[str, Path]] = field(default_factory=list)  # (source label, results JSONL)
    prereview: Path | None = None  # AI pre-review table, imported as suggestions only
    replay: list[Path] = field(default_factory=list)
    jobs: int | None = None


class Console:
    """Everything the routes need, built once at start-up."""

    def __init__(self, cfg: ConsoleConfig) -> None:
        self.cfg = cfg
        t0 = time.perf_counter()
        self.graph = Graph.load(cfg.graph)
        self.store = InMemoryStore(self.graph)
        self.load_seconds = round(time.perf_counter() - t0, 2)
        self.catalog = Catalog(self.store, cfg.fprime)
        self.db = ConsoleDb(cfg.db)
        self.workspace = self._workspace()
        self.replay = load_replay_answers([p for p in cfg.replay if p.exists()])
        self._import_results()
        self.jobs = JobManager(self.db, self.store, self.workspace, self.replay)

    # -- start-up
    def _workspace(self) -> Workspace:
        ws = Workspace(
            self.cfg.fprime, self.cfg.fprime_util, artifacts=self.cfg.artifacts, jobs=self.cfg.jobs
        )
        if ws.fprime is None:
            ws.problems.append("no F´ checkout is configured (start the console with --fprime)")
            return ws
        if not (ws.fprime / ".git").exists():
            ws.problems.append(f"{ws.fprime} is not a git checkout")
            return ws
        stored = self.db.settings().get("base_commit")
        head = subprocess.run(
            ["git", "-C", str(ws.fprime), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
        ws.base_commit = stored or head
        if not stored and head:
            self.db.set_settings({"base_commit": head})
        if not (ws.fprime / "build-fprime-automatic-native-ut").exists():
            ws.problems.append("the unit-test build cache is missing (run scripts/setup_fprime_ut.sh)")
        return ws

    def _import_results(self) -> None:
        suggestions = (
            parse_prereview(self.cfg.prereview) if self.cfg.prereview and self.cfg.prereview.exists() else {}
        )
        for source, path in self.cfg.imports:
            if not path.exists():
                continue
            stem = path.stem.split("__")[0]
            label = display_name(stem)
            if self.db.has_source(source, label):
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                hints = next((v for h, v in suggestions.items() if h.lower() == label.lower()), {})
                verdict, note = hints.get(rec["req_id"], (None, None))
                self.db.add_result(rec, source=source, model_label=label, ai_verdict=verdict, ai_note=note)

    # -- views
    def results_by_req(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for r in self.db.results():
            out.setdefault(r["req_id"], []).append(r)
        return out

    def requirement_rows(self) -> list[dict[str, Any]]:
        by_req = self.results_by_req()
        rows = []
        for req in self.catalog.items.values():
            results = by_req.get(req.req_id, [])
            rows.append(
                {
                    **req.as_dict(),
                    "state": overlay_state(req.base, results),
                    "results": len(results),
                    "agent_ready": req.base == "gap" and self.catalog.agent_support(req.module) is None,
                    "replay": req.req_id in self.replay,
                }
            )
        return rows

    def llm_settings(self) -> dict[str, Any]:
        s = self.db.settings()
        llm = {**DEFAULT_LLM, **(s.get("llm") or {})}
        return {**llm, "api_key_set": bool(s.get("llm_api_key"))}

    def agent_ready(self) -> bool:
        return self.workspace.fprime is not None and not self.workspace.problems


def parse_prereview(path: Path) -> dict[str, dict[str, tuple[str, str]]]:
    """``## <model> …`` sections with ``| REQ | verdict | why |`` rows → {model: {req: (verdict, why)}}."""
    out: dict[str, dict[str, tuple[str, str]]] = {}
    model = None
    for line in path.read_text(encoding="utf-8").splitlines():
        h = re.match(r"^## (\S+)", line)
        if h:
            model = h.group(1)
            out.setdefault(model, {})
            continue
        row = re.match(
            r"^\|\s*([A-Z][A-Z0-9-]*-\d+)\s*\|\s*(relevant|partial|not relevant)\s*\|\s*(.+?)\s*\|\s*$", line
        )
        if row and model:
            out[model][row.group(1)] = (row.group(2).replace(" ", "_"), row.group(3))
    return out


# ------------------------------------------------------------------------------------------------ helpers
def _console(request: Request) -> Console:
    return request.app.state.console


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "the request body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "the request body must be a JSON object")
    return body


def _int(value: Any, name: str, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"{name} must be a whole number") from exc
    if not lo <= v <= hi:
        raise HTTPException(400, f"{name} must be between {lo} and {hi}")
    return v


# ------------------------------------------------------------------------------------------------ routes
async def status(request: Request) -> JSONResponse:
    c = _console(request)
    stats = c.graph.stats()
    llm = c.llm_settings()
    return JSONResponse(
        {
            "graph": {
                "requirements": stats.get("nodes.Requirement", 0),
                "tests": stats.get("nodes.TestCase", 0),
                "functions": stats.get("nodes.Function", 0),
                "files": stats.get("nodes.File", 0),
                "modules": stats.get("nodes.Module", 0),
                "load_seconds": c.load_seconds,
                "source": str(c.cfg.graph.name),
            },
            "workspace": {
                "path": str(c.workspace.fprime) if c.workspace.fprime else None,
                "base_commit": c.workspace.base_commit,
                "problems": c.workspace.problems,
                "ready": c.agent_ready(),
            },
            "llm": {
                "configured": bool(llm["base_url"]),
                "base_url": llm["base_url"],
                "model": llm["model"],
                "label": llm["label"],
            },
            "replay": {"requirements": len(c.replay)},
            "version": __version__,
            "jobs": {"current": c.jobs.current, "queued": c.jobs._queue.qsize()},
        }
    )


async def overview(request: Request) -> JSONResponse:
    c = _console(request)
    rows = c.requirement_rows()
    counts = Counter(r["state"] for r in rows)
    modules: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        modules.setdefault(r["module"], []).append({"req_id": r["req_id"], "state": r["state"]})
    results = c.db.results()
    reviewable = [r for r in results if r["status"] == "passed"]
    return JSONResponse(
        {
            "counts": {s: counts.get(s, 0) for s in STATES},
            "total": len(rows),
            "modules": [
                {"module": m, "items": items}
                for m, items in sorted(modules.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            ],
            "review": {
                "pending": sum(1 for r in reviewable if not r["verdict"]),
                "reviewed": sum(1 for r in reviewable if r["verdict"]),
            },
            "runs": c.db.runs(limit=5),
        }
    )


async def modules(request: Request) -> JSONResponse:
    c = _console(request)
    per: dict[str, Counter[str]] = {}
    for r in c.requirement_rows():
        per.setdefault(r["module"], Counter())[r["state"]] += 1
    out = [
        {
            "module": m,
            "total": sum(cnt.values()),
            "counts": dict(cnt),
            "agent": c.catalog.agent_support(m) is None,
        }
        for m, cnt in sorted(per.items())
    ]
    return JSONResponse(out)


async def requirements(request: Request) -> JSONResponse:
    c = _console(request)
    q = request.query_params
    rows = c.requirement_rows()
    if q.get("module"):
        rows = [r for r in rows if r["module"] == q["module"]]
    if q.get("state"):
        wanted = set(q["state"].split(","))
        rows = [r for r in rows if r["state"] in wanted]
    if q.get("q"):
        terms = q["q"].lower().split()
        rows = [
            r for r in rows if all(t in f"{r['req_id']} {r['text']} {r['module']}".lower() for t in terms)
        ]
    return JSONResponse(rows)


async def requirement(request: Request) -> JSONResponse:
    c = _console(request)
    req_id = request.path_params["req_id"]
    item = c.catalog.items.get(req_id)
    if item is None:
        raise HTTPException(404, f"no requirement {req_id}")
    results = c.results_by_req().get(req_id, [])
    trace = await asyncio.to_thread(c.store.trace_requirement, req_id, 6)
    return JSONResponse(
        {
            **item.as_dict(),
            "state": overlay_state(item.base, results),
            "trace": trace,
            "results": results,
            "agent": {
                "support": c.catalog.agent_support(item.module),
                "workspace_ready": c.agent_ready(),
                "replay": item.req_id in c.replay,
                "eligible": item.base == "gap",
            },
        }
    )


async def search(request: Request) -> JSONResponse:
    c = _console(request)
    q = request.query_params
    text = (q.get("q") or "").strip()
    if not text:
        return JSONResponse([])
    kinds = [k for k in (q.get("kind") or "").split(",") if k in SEARCH_KINDS] or None
    k = _int(q.get("k", 25), "k", 1, 100)
    hits = await asyncio.to_thread(c.store.search, text, k, kinds, q.get("module") or None)
    return JSONResponse([h.as_dict() for h in hits])


async def node(request: Request) -> JSONResponse:
    c = _console(request)
    node_id = request.path_params["node_id"]
    n = c.store.get_node(node_id)
    if n is None:
        raise HTTPException(404, "no such symbol")
    return JSONResponse(
        {**n, "callers": c.store.callers(node_id, 40), "callees": c.store.callees(node_id, 40)}
    )


async def get_settings(request: Request) -> JSONResponse:
    c = _console(request)
    s = c.db.settings()
    return JSONResponse({"llm": c.llm_settings(), "reviewer": s.get("reviewer", "")})


async def put_settings(request: Request) -> JSONResponse:
    c = _console(request)
    body = await _json(request)
    s = c.db.settings()
    updates: dict[str, Any] = {}
    if "llm" in body:
        llm = {**DEFAULT_LLM, **(s.get("llm") or {})}
        incoming = body["llm"] or {}
        if "base_url" in incoming:
            url = str(incoming["base_url"] or "").strip().rstrip("/")
            if url and not re.match(r"^https?://[^\s/]+", url):
                raise HTTPException(400, "the server address must start with http:// or https://")
            llm["base_url"] = re.sub(r"/v1$", "", url)
        for key in ("model", "label"):
            if key in incoming:
                llm[key] = str(incoming[key] or "").strip()[:200]
        if "temperature" in incoming:
            try:
                llm["temperature"] = min(2.0, max(0.0, float(incoming["temperature"])))
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "temperature must be a number") from exc
        if "max_tokens" in incoming:
            llm["max_tokens"] = _int(incoming["max_tokens"], "max_tokens", 256, 32768)
        if "extra_body" in incoming:
            extra = incoming["extra_body"]
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra) if extra.strip() else None
                except json.JSONDecodeError as exc:
                    raise HTTPException(400, "extra request fields must be a JSON object") from exc
            if extra is not None and not isinstance(extra, dict):
                raise HTTPException(400, "extra request fields must be a JSON object")
            llm["extra_body"] = extra
        updates["llm"] = llm
        if incoming.get("api_key"):
            updates["llm_api_key"] = str(incoming["api_key"]).strip()
        if incoming.get("clear_api_key"):
            updates["llm_api_key"] = ""
    if "reviewer" in body:
        updates["reviewer"] = str(body["reviewer"] or "").strip()[:80]
    c.db.set_settings(updates)
    return await get_settings(request)


async def test_llm(request: Request) -> JSONResponse:
    from onprem_genai.platform.smoke import check_chat  # noqa: PLC0415

    c = _console(request)
    llm = c.llm_settings()
    if not llm["base_url"]:
        raise HTTPException(400, "set the model server address first")
    t0 = time.perf_counter()
    try:
        res = await asyncio.to_thread(
            check_chat, llm["base_url"], c.db.settings().get("llm_api_key") or None, llm["model"]
        )
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": _short_error(exc), "seconds": round(time.perf_counter() - t0, 2)}
        )
    return JSONResponse({**res, "seconds": round(time.perf_counter() - t0, 2)})


def _short_error(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    if "ConnectError" in type(exc).__name__ or "Connection refused" in text:
        return "nothing answered at this address; check that the model server is running and reachable"
    if "401" in text or "403" in text:
        return "the server refused the request; check the API key"
    if "404" in text:
        return "no chat endpoint at this address; give the server root, without /v1"
    if "Timeout" in type(exc).__name__:
        return "the server did not answer in time"
    return text[:300]


async def create_run(request: Request) -> JSONResponse:
    c = _console(request)
    body = await _json(request)
    if not c.agent_ready():
        raise HTTPException(409, "the agent cannot run here: " + "; ".join(c.workspace.problems))
    req_ids = list(dict.fromkeys(str(r) for r in body.get("req_ids") or []))
    if not req_ids:
        raise HTTPException(400, "choose at least one requirement")
    if len(req_ids) > 100:
        raise HTTPException(400, "a run can hold at most 100 requirements")
    for r in req_ids:
        item = c.catalog.items.get(r)
        if item is None:
            raise HTTPException(400, f"no requirement {r}")
        if item.base != "gap":
            raise HTTPException(
                400, f"{r} is not a gap: it is already cited by a test or not verified by test"
            )
        why = c.catalog.agent_support(item.module)
        if why:
            raise HTTPException(400, f"{r}: the agent cannot work on {item.module} ({why})")
    kind = body.get("model_kind", "endpoint")
    attempts = _int(body.get("attempts", 3), "attempts", 1, 6)
    mutants = _int(body.get("mutants", 4), "mutants", 0, 12)
    if kind == "replay":
        missing = [r for r in req_ids if r not in c.replay]
        if missing:
            raise HTTPException(400, f"no recorded answer to replay for {', '.join(missing[:5])}")
        label = "Recorded answers of " + " and ".join(sorted({c.replay[r]["label"] for r in req_ids}))
        options: dict[str, Any] = {}
    elif kind == "endpoint":
        llm = c.llm_settings()
        if not llm["base_url"]:
            raise HTTPException(400, "set the model server in Settings first")
        label = llm["label"] or llm["model"]
        options = {k: llm[k] for k in ("base_url", "model", "temperature", "max_tokens", "extra_body")}
    else:
        raise HTTPException(400, "model_kind must be 'endpoint' or 'replay'")
    run_id = c.jobs.submit(RunRequest(req_ids, kind, attempts, mutants), label, options)
    return JSONResponse({"id": run_id}, status_code=201)


async def list_runs(request: Request) -> JSONResponse:
    c = _console(request)
    out = []
    for run in c.db.runs(limit=100):
        res = c.db.results(run_id=run["id"])
        out.append({**run, "passed": sum(1 for r in res if r["status"] == "passed"), "finished": len(res)})
    return JSONResponse(out)


async def get_run(request: Request) -> JSONResponse:
    c = _console(request)
    run_id = _int(request.path_params["run_id"], "run", 1, 10**9)
    run = c.db.run(run_id)
    if run is None:
        raise HTTPException(404, f"no run {run_id}")
    return JSONResponse({**run, "results": c.db.results(run_id=run_id), "events": c.db.events(run_id)})


async def run_events(request: Request) -> EventSourceResponse:
    c = _console(request)
    run_id = _int(request.path_params["run_id"], "run", 1, 10**9)
    if c.db.run(run_id) is None:
        raise HTTPException(404, f"no run {run_id}")
    after = int(request.query_params.get("after", -1))

    async def stream() -> AsyncIterator[dict[str, str]]:
        q = c.jobs.subscribe(run_id)
        try:
            last = after
            for ev in c.db.events(run_id, after):
                last = ev["seq"]
                yield {"id": str(ev["seq"]), "data": json.dumps(ev)}
            while True:
                run = c.db.run(run_id)
                if run and run["status"] in ("done", "failed", "cancelled") and q.empty():
                    return
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield {"comment": "keep-alive"}
                    continue
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield {"id": str(ev["seq"]), "data": json.dumps(ev)}
        finally:
            c.jobs.unsubscribe(run_id, q)

    return EventSourceResponse(stream())


async def stop_run(request: Request) -> JSONResponse:
    c = _console(request)
    run_id = _int(request.path_params["run_id"], "run", 1, 10**9)
    try:
        return JSONResponse({"status": c.jobs.stop(run_id)})
    except KeyError as exc:
        raise HTTPException(404, f"no run {run_id}") from exc


async def reviews(request: Request) -> JSONResponse:
    c = _console(request)
    which = request.query_params.get("filter", "pending")
    rows = [r for r in c.db.results(status="passed")]
    if which == "pending":
        rows = [r for r in rows if not r["verdict"]]
    elif which == "reviewed":
        rows = [r for r in rows if r["verdict"]]
    for r in rows:
        item = c.catalog.items.get(r["req_id"])
        r["text"] = item.text if item else ""
    return JSONResponse(rows)


async def review(request: Request) -> JSONResponse:
    c = _console(request)
    rid = _int(request.path_params["result_id"], "result", 1, 10**9)
    res = c.db.result(rid)
    if res is None:
        raise HTTPException(404, "no such result")
    item = c.catalog.items.get(res["req_id"])
    return JSONResponse({**res, "requirement": item.as_dict() if item else None})


async def set_review(request: Request) -> JSONResponse:
    c = _console(request)
    rid = _int(request.path_params["result_id"], "result", 1, 10**9)
    res = c.db.result(rid)
    if res is None or res["status"] != "passed":
        raise HTTPException(404, "no verified test with this id")
    body = await _json(request)
    verdict = body.get("verdict")
    if verdict is not None and verdict not in VERDICTS:
        raise HTTPException(400, "the verdict must be relevant, partial or not_relevant")
    reviewer = str(body.get("reviewer") or c.db.settings().get("reviewer") or "").strip()[:80]
    c.db.set_verdict(rid, verdict, str(body.get("note") or "")[:2000], reviewer)
    return await review(request)


async def export_reviews(request: Request) -> Response:
    c = _console(request)
    rows = c.db.results(status="passed")
    lines = [
        "# Review sheet: generated unit tests",
        "",
        f"Exported {time.strftime('%Y-%m-%d %H:%M')} from the engineering console. Verdicts are human",
        "reviews of whether each test exercises the behaviour its requirement states and checks the outcome.",
        "",
        "| Requirement | Model | Source | Commit | Mutants killed | Verdict | Reviewer | Note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda x: (x["req_id"], x["model_label"])):
        mut = f"{r['mutants_killed']}/{r['mutants_valid']}" if r["mutants_valid"] else "n/a"
        note = (r["note"] or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {r['req_id']} | {r['model_label']} | {r['source']} | {(r['commit'] or '')[:10]} | {mut} | "
            f"{(r['verdict'] or 'not reviewed').replace('_', ' ')} | {r['reviewer'] or ''} | {note} |"
        )
    body = "\n".join(lines) + "\n"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="review-sheet-{time.strftime("%Y%m%d")}.md"'},
    )


async def sizing_options(request: Request) -> JSONResponse:
    from onprem_genai.sizing.planner import load_scenarios  # noqa: PLC0415
    from onprem_genai.sizing.specs import load_formats, load_gpus, load_models  # noqa: PLC0415

    wf, kf = load_formats()
    models = []
    for k, m in load_models().items():
        try:
            m.require("params_total", "n_layers", "kv_heads", "head_dim")
        except Exception:  # incomplete specs are not plannable
            continue
        models.append(
            {
                "key": k,
                "name": m.display_name,
                "params_total": m.params_total,
                "params_active": m.params_active,
                "moe": bool(m.num_experts),
            }
        )
    return JSONResponse(
        {
            "models": models,
            "gpus": [
                {
                    "key": k,
                    "name": g.name,
                    "memory_gb": g.memory_gb,
                    "bandwidth_gbs": g.bandwidth_gbs,
                    "arch": g.arch,
                }
                for k, g in load_gpus().items()
            ],
            "weights": [{"key": k, "name": getattr(v, "name", k)} for k, v in wf.items()],
            "kv": [{"key": k, "name": getattr(v, "name", k)} for k, v in kf.items()],
            "scenarios": [s.model_dump() for s in load_scenarios().values()],
            "calibrations": [{"key": v["key"], "label": v["label"]} for v in _calibrations().values()],
        }
    )


def _calibrations() -> dict[str, dict[str, Any]]:
    from onprem_genai.sizing.data import __file__ as data_init  # noqa: PLC0415

    labels = {"llamacpp_t4": "llama.cpp (measured)", "vllm_t4": "vLLM (measured)"}
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(Path(data_init).parent.glob("calibration_*.json")):
        key = p.stem.removeprefix("calibration_")
        out[key] = {"key": key, "label": labels.get(key, key), "path": str(p)}
    out["datasheet"] = {"key": "datasheet", "label": "Datasheet (not measured)"}
    return out


async def sizing_plan(request: Request) -> JSONResponse:
    from onprem_genai.sizing.performance import Calibration  # noqa: PLC0415
    from onprem_genai.sizing.planner import RequestClass, best_plan_per_gpu, load_scenarios  # noqa: PLC0415
    from onprem_genai.sizing.specs import load_formats, load_gpus, load_models  # noqa: PLC0415

    body = await _json(request)
    models, gpus = load_models(), load_gpus()
    wf, kf = load_formats()
    model = models.get(str(body.get("model")))
    if model is None:
        raise HTTPException(400, "unknown model")
    weights, kv = wf.get(str(body.get("weights", "q4_k_m"))), kf.get(str(body.get("kv", "f16")))
    if weights is None or kv is None:
        raise HTTPException(400, "unknown weight or KV-cache format")
    scenarios = load_scenarios()
    sc = scenarios.get(str(body.get("scenario", "chat_agents")))
    if sc is None:
        raise HTTPException(400, "unknown workload")
    over = body.get("overrides") or {}
    try:
        if "request_classes" in over:
            sc = sc.model_copy(
                update={"request_classes": [RequestClass(**rc) for rc in over["request_classes"]]}
            )
        for key in ("peak_active_fraction", "min_decode_tps_per_sequence", "headroom"):
            if key in over:
                sc = sc.model_copy(update={key: float(over[key])})
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"invalid workload values: {exc}") from exc
    engineers = _int(body.get("engineers", 100), "engineers", 1, 100000)
    chosen = [g for g in body.get("gpus") or [] if g in gpus]
    pool = {k: gpus[k] for k in chosen} if chosen else gpus
    cal_key = str(body.get("calibration", "llamacpp_t4"))
    cal = _calibrations().get(cal_key)
    calib = (
        Calibration(**json.loads(Path(cal["path"]).read_text(encoding="utf-8")))
        if cal and cal.get("path")
        else Calibration()
    )
    plans = await asyncio.to_thread(
        best_plan_per_gpu, model, weights, kv, pool, sc, engineers=engineers, calib=calib
    )
    return JSONResponse(
        {
            "model": {"key": body.get("model"), "name": model.display_name},
            "scenario": sc.model_dump(),
            "engineers": engineers,
            "calibration": cal_key,
            "plans": [
                {**p.as_dict(), "gpu_name": gpus[p.gpu].name if p.gpu in gpus else p.gpu} for p in plans
            ],
        }
    )


async def index(request: Request) -> Response:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


async def http_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, HTTPException)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        resp = await call_next(request)
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'self'",
        )
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp


def create_app(cfg: ConsoleConfig) -> Starlette:
    console = Console(cfg)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        console.jobs.start()
        yield
        await console.jobs.close()

    routes = [
        Route("/", index),
        Route("/api/status", status),
        Route("/api/overview", overview),
        Route("/api/modules", modules),
        Route("/api/requirements", requirements),
        Route("/api/requirements/{req_id}", requirement),
        Route("/api/search", search),
        Route("/api/nodes/{node_id:path}", node),
        Route("/api/settings", get_settings, methods=["GET"]),
        Route("/api/settings", put_settings, methods=["PUT"]),
        Route("/api/settings/test", test_llm, methods=["POST"]),
        Route("/api/runs", list_runs, methods=["GET"]),
        Route("/api/runs", create_run, methods=["POST"]),
        Route("/api/runs/{run_id}", get_run),
        Route("/api/runs/{run_id}/events", run_events),
        Route("/api/runs/{run_id}/stop", stop_run, methods=["POST"]),
        Route("/api/reviews", reviews),
        Route("/api/reviews/export", export_reviews),
        Route("/api/reviews/{result_id}", review, methods=["GET"]),
        Route("/api/reviews/{result_id}", set_review, methods=["PUT"]),
        Route("/api/sizing/options", sizing_options),
        Route("/api/sizing/plan", sizing_plan, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={HTTPException: http_error},
        middleware=[Middleware(SecurityHeaders), Middleware(GZipMiddleware, minimum_size=1024)],
    )
    app.state.console = console
    return app
