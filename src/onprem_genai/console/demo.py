"""Static demo of the console: the API's answers written to files, for a read-only site such as GitHub Pages.

The demo is built from the same graph, benchmark results and console code as the real thing, plus one
recorded agent run (``demo/console/recorded-run.json``) that the page can play back step by step. The front
end switches to the files when the page carries ``data-oge-demo``; see ``static/js/demo.js``.

What a static site cannot do is left out on purpose: starting agent runs, settings, free-text search (the
example searches are precomputed) and arbitrary sizing assumptions (a grid of common ones is precomputed).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from starlette.testclient import TestClient

from onprem_genai.console.app import DEFAULT_LLM, STATIC, ConsoleConfig, create_app
from onprem_genai.console.db import ConsoleDb

# Must match EXAMPLES in static/js/pages/search.js and the kinds offered there (tested).
SEARCH_EXAMPLES = (
    "retry sending when the driver asks for a retry",
    "parameter file load failure",
    "SVC-COMSTUB-004",
    "frame context restored on return",
)
SEARCH_KINDS = ("", "Function", "TestCase", "Requirement", "DocChunk")
SEARCH_K = 30
# Sizing grid: every model, weight format, workload and efficiency source, KV cache in FP16, these team sizes.
DEMO_ENGINEERS = (25, 50, 100, 200, 500, 1000)


def node_file(node_id: str) -> str:
    """File name of a graph node in the demo (same function in demo.js)."""
    return hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:20] + ".json"  # a file name, not security


def search_key(q: str, kind: str) -> str:
    return f"{kind}|{q}"


class _Writer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.files = 0
        self.bytes = 0

    def write(self, rel: str, data: Any) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        path.write_text(text, encoding="utf-8")
        self.files += 1
        self.bytes += len(text.encode("utf-8"))


def export_demo(
    cfg: ConsoleConfig, recorded: list[Path], out: Path, *, sizing: bool = True
) -> dict[str, int]:
    """Write the demo site to ``out``: the console's static files, an index page in demo mode and data/.

    Nothing about the exporting machine's model server is written: the demo shows no server and no key.
    """
    db = ConsoleDb(cfg.db)
    if not db.runs():
        for path in recorded:
            db.import_run(json.loads(path.read_text(encoding="utf-8")))
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out / "static", ignore=shutil.ignore_patterns("index.html"))
    snapshot = time.strftime("%Y-%m-%d")
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    index = index.replace(
        '<html lang="en">', f'<html lang="en" data-oge-demo="data/" data-oge-snapshot="{snapshot}">'
    )
    (out / "index.html").write_text(index, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    w = _Writer(out / "data")
    nodes: set[str] = set()
    with TestClient(create_app(cfg)) as c:

        def get(path: str) -> Any:
            r = c.get(f"/api{path}")
            r.raise_for_status()
            return r.json()

        status = get("/status")
        status["workspace"] = {
            "path": None,
            "base_commit": status["workspace"]["base_commit"],
            "problems": ["this is a static demo: agent runs need the console on your own site"],
            "ready": False,
        }
        status["llm"] = {"configured": False, "base_url": "", "model": "", "label": ""}
        status["demo"] = {"snapshot": snapshot}
        w.write("status.json", status)
        w.write("overview.json", get("/overview"))
        w.write("modules.json", get("/modules"))
        rows = get("/requirements")
        w.write("requirements.json", rows)
        for row in rows:
            detail = get(f"/requirements/{quote(row['req_id'], safe='')}")
            w.write(f"req/{row['req_id']}.json", detail)
            for group in ("suggested_tests", "related_code"):
                nodes.update(x["id"] for x in detail["trace"].get(group, []))

        runs = get("/runs")
        w.write("runs.json", runs)
        for run in runs:
            w.write(f"runs/{run['id']}.json", get(f"/runs/{run['id']}"))

        reviews = get("/reviews?filter=all")
        w.write("reviews.json", reviews)
        for item in reviews:
            w.write(f"reviews/{item['id']}.json", get(f"/reviews/{item['id']}"))
        sheet = c.get("/api/reviews/export")
        sheet.raise_for_status()
        w.write("review-sheet.md", sheet.text)
        w.write("settings.json", {"llm": {**DEFAULT_LLM, "api_key_set": False}, "reviewer": ""})

        searches: dict[str, Any] = {}
        for q in SEARCH_EXAMPLES:
            for kind in SEARCH_KINDS:
                hits = get(f"/search?q={quote(q)}&k={SEARCH_K}" + (f"&kind={kind}" if kind else ""))
                searches[search_key(q, kind)] = hits
                nodes.update(h["id"] for h in hits)
        w.write("search.json", searches)
        for node_id in sorted(nodes):
            w.write(f"nodes/{node_file(node_id)}", get(f"/nodes/{quote(node_id, safe='')}"))

        _export_sizing(c, w, get("/sizing/options"), sizing=sizing)
        w.write("meta.json", {"snapshot": snapshot, "engineers": list(DEMO_ENGINEERS), "kv": "f16"})
    return {"files": w.files, "bytes": w.bytes, "nodes": len(nodes)}


def _export_sizing(c: TestClient, w: _Writer, options: dict[str, Any], *, sizing: bool) -> None:
    """Sizing options, and one file of precomputed plans per model and efficiency source."""
    w.write("sizing/options.json", options)
    for model in options["models"] if sizing else []:
        for cal in options["calibrations"]:
            grid: dict[str, Any] = {}
            for weights in options["weights"]:
                for scenario in options["scenarios"]:
                    for engineers in DEMO_ENGINEERS:
                        body = {
                            "model": model["key"],
                            "weights": weights["key"],
                            "kv": "f16",
                            "scenario": scenario["key"],
                            "engineers": engineers,
                            "calibration": cal["key"],
                        }
                        r = c.post("/api/sizing/plan", json=body)
                        grid[f"{weights['key']}|{scenario['key']}|{engineers}"] = (
                            r.json() if r.status_code == 200 else {"error": r.json().get("error")}
                        )
            w.write(f"sizing/{model['key']}__{cal['key']}.json", grid)
