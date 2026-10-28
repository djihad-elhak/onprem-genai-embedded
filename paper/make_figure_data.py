"""Write the data behind the paper's plots (paper/figures/*.dat) from the stored benchmark results.

uv run python paper/make_figure_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

from onprem_genai.agent.runner import failure_causes

ROOT = Path(__file__).resolve().parents[1]
RUN2 = ROOT / "docs/results/bench/run2-2026-10-28"
RUN3 = ROOT / "docs/results/bench/run3-2026-10-28"
OUT = Path(__file__).with_name("figures")
MODELS = {"qwen": "qwen3-coder-30b-a3b__llamacpp", "devstral": "devstral-small-2-24b__llamacpp"}

# Failure causes grouped for the stacked bars (column name -> classifier labels).
GROUPS = {
    "dispatch": ["dispatch call on the wrong object or a passive component"],
    "qualified": ["namespace-qualified method definition"],
    "compile": ["other compile error", "-Werror: C-style cast or deprecated API"],
    "policy": ["answer missing a block", "reused an existing method or test name", "other policy rejection"],
    "assertion": ["F´ assertion in the component (precondition broken)"],
    "expected": ["wrong expected value"],
}


def serving() -> None:
    files = {
        "qwenllama": "qwen3-coder-30b-a3b__llamacpp",
        "qwenvllm": "qwen3-coder-30b-a3b__vllm",
        "devllama": "devstral-small-2-24b__llamacpp",
    }
    rows = ["streams " + " ".join(f"{k} {k}ttft" for k in files)]
    levels = {
        k: json.loads((RUN3 / f"serving/{v}.json").read_text())["profiles"]["chat"] for k, v in files.items()
    }
    for i, lvl in enumerate(levels["qwenllama"]):
        cells = [str(lvl["concurrency"])]
        for k in files:
            x = levels[k][i]
            cells += [f"{1000 / x['tpot_p50_ms']:.1f}", f"{x['ttft_p50_s']:.2f}"]
        rows.append(" ".join(cells))
    (OUT / "serving_chat.dat").write_text("\n".join(rows) + "\n")


def causes() -> None:
    rows = ["run " + " ".join(GROUPS)]
    for label, path, model in [
        ("Qwen v1", RUN2 / "agent-v1", "qwen"),
        ("Qwen v2", RUN3 / "agent-v2", "qwen"),
        ("Devstral v1", RUN2 / "agent-v1", "devstral"),
        ("Devstral v2", RUN3 / "agent-v2", "devstral"),
    ]:
        recs = [
            json.loads(line) for line in (path / f"{MODELS[model]}.jsonl").read_text().splitlines() if line
        ]
        fc = failure_causes(recs)
        counts = [sum(fc.get(c, {}).get("attempts", 0) for c in cs) for cs in GROUPS.values()]
        rows.append(f"{{{label}}} " + " ".join(map(str, counts)))
    (OUT / "failure_causes.dat").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    serving()
    causes()
    for f in sorted(OUT.glob("*.dat")):
        print(f"--- {f.name}\n{f.read_text()}")
