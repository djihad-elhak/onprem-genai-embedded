"""Collect the data of the interactive replay page (demo/web/index.html) from the stored benchmark results.

    uv run python demo/web/extract.py   # writes demo/web/data.json

Nothing is computed by hand: every number comes from docs/results (runs 2 and 3) and the F´ graph.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from onprem_genai.knowledge.model import Graph, NodeType

ROOT = Path(__file__).resolve().parents[2]
RUN2 = ROOT / "docs/results/bench/run2-2026-10-28"
RUN3 = ROOT / "docs/results/bench/run3-2026-10-28"
MODELS = {"qwen": "qwen3-coder-30b-a3b__llamacpp", "devstral": "devstral-small-2-24b__llamacpp"}
# Runs shown step by step: a repaired pass, a first-attempt pass, a failure.
SERVING_FIELDS = ("concurrency", "output_tps", "requests_per_s", "ttft_p50_s", "tpot_p50_ms", "n_errors")
REPLAYS = [("qwen", "SVC-COMRETRY-002"), ("qwen", "SVC-COMSTUB-007"), ("qwen", "PRMDB-002")]


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def assert_lines(history: list[dict]) -> dict[str, str]:
    """Source line of each F´ assertion a failed test hit (the agent shows the same line to the model)."""
    out = {}
    for h in history:
        for file, line in re.findall(r'Assert: "([\w/.]+):(\d+)"', h["detail"]):
            src = ROOT / "third_party/fprime" / file
            if src.exists():
                out[f"{file}:{line}"] = src.read_text().splitlines()[int(line) - 1].strip()
    return out


def summary(path: Path) -> dict:
    s = json.loads(path.read_text())
    keep = (
        "targets",
        "status",
        "first_attempt_compile_rate",
        "median_wall_seconds",
        "mutation",
        "failure_causes",
    )
    return {k: s.get(k) for k in keep}


def requirement_texts() -> dict[str, dict]:
    g = Graph.load(ROOT / "artifacts/fprime_graph.jsonl.gz")
    out = {}
    for n in g.of_type(NodeType.REQUIREMENT):
        p = n.props
        out[p.get("req_id") or n.id.split(":", 1)[-1]] = {
            "text": p.get("text", ""),
            "verification": p.get("verification", ""),
            "file": p.get("file", ""),
        }
    return out


def main() -> None:
    reqs = requirement_texts()
    runs = {k: load_jsonl(RUN3 / f"agent-v2/{v}.jsonl") for k, v in MODELS.items()}
    v1 = {k: load_jsonl(RUN2 / f"agent-v1/{v}.jsonl") for k, v in MODELS.items()}

    board = []
    for i, r in enumerate(runs["qwen"]):
        d = runs["devstral"][i]
        assert d["req_id"] == r["req_id"]
        board.append(
            {
                "req_id": r["req_id"],
                "module": r["module"],
                "text": reqs.get(r["req_id"], {}).get("text", ""),
                **{
                    m: {
                        "status": x["status"],
                        "steps": [h["stage"] for h in x["history"]],
                        "seconds": x["wall_seconds"],
                        "v1": next(y["status"] for y in v1[m] if y["req_id"] == r["req_id"]),
                    }
                    for m, x in (("qwen", r), ("devstral", d))
                },
            }
        )

    replays = []
    for model, rid in REPLAYS:
        r = next(x for x in runs[model] if x["req_id"] == rid)
        m = r["metrics"]
        replays.append(
            {
                "model": model,
                "req_id": rid,
                "module": r["module"],
                "requirement": reqs.get(rid, {}),
                "status": r["status"],
                "reason": r["reason"],
                "attempts": r["attempts"],
                "commit": r["commit"],
                "wall_seconds": r["wall_seconds"],
                "history": r["history"],
                "assert_lines": assert_lines(r["history"]),
                "last_answer": r["last_answer"],
                "diff": r["diff"],
                "metrics": {k: v for k, v in m.items() if k != "mutation"},
                "mutation": m.get("mutation"),
            }
        )

    serving = {}
    for k, v in {**MODELS, "qwen_vllm": "qwen3-coder-30b-a3b__vllm"}.items():
        raw = json.loads((RUN3 / f"serving/{v}.json").read_text())
        serving[k] = {
            "engine": raw["config"]["engine"],
            "profiles": {
                name: [{f: lvl[f] for f in SERVING_FIELDS} for lvl in levels]
                for name, levels in raw["profiles"].items()
            },
        }
    trace = json.loads((RUN2 / "traceability.json").read_text())
    data = {
        "board": board,
        "replays": replays,
        "summaries": {
            ver: {k: summary(path / f"{v}.summary.json") for k, v in MODELS.items()}
            for ver, path in (("v1", RUN2 / "agent-v1"), ("v2", RUN3 / "agent-v2"))
        },
        "serving": serving,
        "traceability": {
            "dataset": {k: trace["dataset"][k] for k in ("requirements", "candidates", "embedder")},
            "methods": {
                name: {k: m["metrics"][k] for k in ("ap", "recall@1", "recall@10")}
                for name, m in trace["methods"].items()
            },
        },
    }
    out = Path(__file__).with_name("data.json")
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    # The page: the template with the data inlined, wrapped in a document so the browser uses standards mode.
    template = Path(__file__).with_name("page.html").read_text()
    page = template.replace("/*DATA*/", json.dumps(data, ensure_ascii=False))
    html = Path(__file__).with_name("index.html")
    html.write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        "<style>body{margin:0}[hidden]{display:none!important}</style>\n</head>\n<body>\n"
        + page
        + "\n</body>\n</html>\n"
    )
    print(f"wrote {html} ({html.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
