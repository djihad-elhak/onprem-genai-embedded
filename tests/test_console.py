"""Engineering console: HTTP API, persistence and, on real F´, a full agent run started from the API."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

from onprem_genai.console.app import ConsoleConfig, create_app, parse_prereview
from onprem_genai.console.catalog import overlay_state
from onprem_genai.console.db import ConsoleDb
from onprem_genai.console.jobs import display_name, load_replay_answers
from onprem_genai.knowledge.model import Graph

ANSWER = (
    "```cpp tester\nvoid FooTester::testX() { ASSERT_EQ(1, 1); }\n```\n\n```cpp main\nTEST(Foo, X) { }\n```\n"
)


def _record(req_id: str, status: str = "passed", answer: str = ANSWER) -> dict:
    return {
        "req_id": req_id,
        "module": "Svc/Foo",
        "status": status,
        "reason": "",
        "attempts": 1,
        "commit": "0123456789abcdef" if status == "passed" else None,
        "wall_seconds": 12.5,
        "metrics": {"mutation": {"valid": 4, "killed": 3, "mutants": []}, "test_names": ["Foo.X"]},
        "history": [{"attempt": 1, "stage": status if status == "passed" else "build", "detail": "Foo.X"}],
        "diff": "+++ b/Svc/Foo/test/ut/FooTester.cpp\n+void FooTester::testX() {}\n",
        "last_answer": answer,
    }


@pytest.fixture
def client(tmp_path: Path, mini_graph: Graph):
    graph = tmp_path / "graph.jsonl.gz"
    mini_graph.save(graph)
    results = tmp_path / "foo-model-7b__llamacpp.jsonl"
    results.write_text(
        "\n".join(json.dumps(r) for r in (_record("FOO-004"), _record("FOO-002", "failed"))) + "\n"
    )
    review = tmp_path / "ai-prereview.md"
    review.write_text(
        "## Foo-Model-7B — 1 relevant\n\n| Requirement | Verdict | Why |\n|---|---|---|\n"
        "| FOO-004 | relevant | checks it |\n"
    )
    cfg = ConsoleConfig(
        graph=graph,
        db=tmp_path / "console.db",
        imports=[("Benchmark", results)],
        prereview=review,
        replay=[results],
        artifacts=tmp_path,
    )
    with TestClient(create_app(cfg)) as c:
        yield c


def test_status_reports_a_missing_workspace(client: TestClient) -> None:
    s = client.get("/api/status").json()
    assert s["graph"]["requirements"] >= 2
    assert s["workspace"]["ready"] is False
    assert "--fprime" in s["workspace"]["problems"][0]
    assert s["replay"]["requirements"] == 1  # only the verified, self-contained answer


def test_overview_requirements_and_detail(client: TestClient) -> None:
    o = client.get("/api/overview").json()
    assert o["total"] == sum(o["counts"].values())
    assert o["review"] == {"pending": 1, "reviewed": 0}
    rows = {r["req_id"]: r for r in client.get("/api/requirements").json()}
    assert rows["FOO-004"]["state"] == "generated"  # imported verified test, not reviewed yet
    assert rows["FOO-002"]["state"] == "covered"  # a tagged test wins over agent attempts
    assert rows["FOO-003"]["state"] == "not_by_test"
    d = client.get("/api/requirements/FOO-004").json()
    assert d["agent"]["support"] == "no F´ workspace is configured"
    assert {"explicit_tests", "suggested_tests", "related_code"} <= set(d["trace"])
    assert client.get("/api/requirements/NOPE-1").status_code == 404


def test_review_verdicts_and_export(client: TestClient) -> None:
    [item] = client.get("/api/reviews").json()
    assert item["model_label"] == "Foo-Model-7B"
    assert item["ai_verdict"] == "relevant"
    assert client.put(f"/api/reviews/{item['id']}", json={"verdict": "maybe"}).status_code == 400
    r = client.put(
        f"/api/reviews/{item['id']}", json={"verdict": "partial", "note": "one case of two"}
    ).json()
    assert r["verdict"] == "partial"
    assert r["note"] == "one case of two"
    assert client.get("/api/reviews").json() == []
    assert {r["req_id"]: r["state"] for r in client.get("/api/requirements").json()}["FOO-004"] == "accepted"
    sheet = client.get("/api/reviews/export")
    assert "attachment" in sheet.headers["content-disposition"]
    assert "| FOO-004 | Foo-Model-7B | Benchmark | 0123456789 | 3/4 | partial |" in sheet.text


def test_api_key_is_write_only_and_settings_are_validated(client: TestClient) -> None:
    r = client.put(
        "/api/settings", json={"llm": {"base_url": "http://gpu:8080/v1/", "api_key": "s3cret"}}
    ).json()
    assert r["llm"]["base_url"] == "http://gpu:8080"
    assert r["llm"]["api_key_set"] is True
    assert "s3cret" not in client.get("/api/settings").text
    assert client.put("/api/settings", json={"llm": {"base_url": "ftp://x"}}).status_code == 400
    assert client.put("/api/settings", json={"llm": {"extra_body": "[1]"}}).status_code == 400
    r = client.put("/api/settings", json={"llm": {"clear_api_key": True}}).json()
    assert r["llm"]["api_key_set"] is False


def test_runs_need_a_workspace_and_valid_requirements(client: TestClient) -> None:
    r = client.post("/api/runs", json={"req_ids": ["FOO-004"], "model_kind": "replay"})
    assert r.status_code == 409
    assert "F´" in r.json()["error"]
    assert client.get("/api/runs").json() == []


def test_search_node_sizing_and_security_headers(client: TestClient) -> None:
    hits = client.get("/api/search?q=run&k=5").json()
    assert hits
    assert {"id", "kind", "title", "location"} <= set(hits[0])
    node = client.get(f"/api/nodes/{quote(hits[0]['id'], safe='')}").json()
    assert {"callers", "callees"} <= set(node)
    opts = client.get("/api/sizing/options").json()
    assert {c["key"] for c in opts["calibrations"]} >= {"llamacpp_t4", "datasheet"}
    plan = client.post(
        "/api/sizing/plan",
        json={
            "model": "qwen3-coder-30b-a3b",
            "engineers": 100,
            "scenario": "chat_agents",
            "gpus": ["l4", "h100-sxm"],
        },
    ).json()
    assert {p["gpu"]: p["total_gpus"] for p in plan["plans"]} == {
        "l4": 6,
        "h100-sxm": 1,
    }  # docs/results/sizing
    page = client.get("/")
    assert page.status_code == 200
    assert "default-src 'self'" in page.headers["content-security-policy"]
    css = client.get("/static/vendor/hds/css/hds.min.css", headers={"Accept-Encoding": "gzip"})
    assert css.status_code == 200
    assert css.headers["content-encoding"] == "gzip"  # the 0.5 MB design system stylesheet travels as ~50 kB
    assert client.get("/api/status").json()["version"]


def test_helpers(tmp_path: Path) -> None:
    assert display_name("qwen3-coder-30b-a3b") == "Qwen3-Coder-30B-A3B"
    assert display_name("devstral-small-2-24b") == "Devstral-Small-2-24B"
    p = tmp_path / "x__y.jsonl"
    partial = "```cpp tester\nvoid FooTester::testX() {}\n```\n"  # a repair answer resending one block
    p.write_text("\n".join(json.dumps(_record(r, answer=a)) for r, a in (("A-1", ANSWER), ("A-2", partial))))
    assert set(load_replay_answers([p])) == {"A-1"}
    assert overlay_state("covered", []) == "covered"
    assert overlay_state("gap", [{"status": "passed", "verdict": None}]) == "generated"
    assert overlay_state("gap", [{"status": "passed", "verdict": "not_relevant"}]) == "rejected"
    assert overlay_state("gap", [{"status": "failed", "verdict": None}]) == "attempted"
    md = tmp_path / "r.md"
    md.write_text("## M-1 x\n| R-1 | not relevant | wrong port |\n")
    assert parse_prereview(md) == {"M-1": {"R-1": ("not_relevant", "wrong port")}}


def test_db_marks_interrupted_runs_failed(tmp_path: Path) -> None:
    db = ConsoleDb(tmp_path / "c.db")
    run = db.create_run("replay", "x", {}, ["A-1"])
    db.update_run(run, status="running")
    reopened = ConsoleDb(tmp_path / "c.db").run(run)
    assert reopened is not None
    assert reopened["status"] == "failed"


# ------------------------------------------------------------------------------- real F´
FPRIME = Path("third_party/fprime")
REPLAY = Path("demo/qwen3-coder-run3-replay.json")


@pytest.mark.fprime
def test_console_runs_the_agent_on_fprime(tmp_path: Path) -> None:
    from onprem_genai.agent.fprime import FprimeWorkspace  # noqa: PLC0415
    from onprem_genai.knowledge.fprime.ingest import ingest_fprime  # noqa: PLC0415

    ws_check = FprimeWorkspace(FPRIME) if FPRIME.exists() else None
    if ws_check is None or not (FPRIME / "build-fprime-automatic-native-ut").is_dir():
        pytest.skip("run scripts/setup_fprime_ut.sh")
    if ws_check.changed_files():
        pytest.skip("F´ checkout has local changes")
    origin = ws_check.head()
    g, _ = ingest_fprime(FPRIME, top_dirs=("Svc",))
    graph = tmp_path / "g.jsonl.gz"
    g.save(graph)
    answers = json.loads(REPLAY.read_text())
    results = tmp_path / "qwen3-coder-30b-a3b__llamacpp.jsonl"
    results.write_text(
        json.dumps(
            {"req_id": "SVC-COMSTUB-007", "status": "passed", "last_answer": answers["SVC-COMSTUB-007"][0]}
        )
        + "\n"
    )
    cfg = ConsoleConfig(
        graph=graph, db=tmp_path / "c.db", fprime=FPRIME, replay=[results], artifacts=tmp_path
    )
    try:
        with TestClient(create_app(cfg)) as c:
            assert c.get("/api/status").json()["workspace"]["ready"] is True
            run_id = c.post(
                "/api/runs", json={"req_ids": ["SVC-COMSTUB-007"], "model_kind": "replay", "mutants": 1}
            ).json()["id"]
            deadline = time.monotonic() + 600
            while c.get(f"/api/runs/{run_id}").json()["status"] not in ("done", "failed", "cancelled"):
                assert time.monotonic() < deadline
                time.sleep(1)
            run = c.get(f"/api/runs/{run_id}").json()
            assert run["status"] == "done", run["error"]
            nodes = [e["node"] for e in run["events"] if e["type"] == "step"]
            assert nodes[:3] == ["prepare", "gather", "generate"]
            assert "commit" in nodes
            [res] = run["results"]
            assert res["status"] == "passed"
            assert res["model_label"] == "Qwen3-Coder-30B-A3B (recorded)"
            assert c.get("/api/reviews").json()[0]["req_id"] == "SVC-COMSTUB-007"
            with c.stream(
                "GET", f"/api/runs/{run_id}/events"
            ) as s:  # finished runs replay their stored events
                assert sum(1 for line in s.iter_lines() if line.startswith("data:")) == len(run["events"])
    finally:
        subprocess.run(["git", "-C", str(FPRIME), "checkout", "-q", "--detach", origin], check=False)
        subprocess.run(
            ["git", "-C", str(FPRIME), "branch", "-D", "oge-console/run-1"], check=False, capture_output=True
        )


def test_static_demo_export(tmp_path: Path, mini_graph: Graph) -> None:
    from onprem_genai.console.demo import DEMO_ENGINEERS, SEARCH_EXAMPLES, export_demo, node_file  # noqa: PLC0415

    graph = tmp_path / "graph.jsonl.gz"
    mini_graph.save(graph)
    src = ConsoleDb(tmp_path / "src.db")
    run = src.create_run("replay", "Recorded answers", {"attempts": 1, "mutants": 0}, ["FOO-004"])
    rid = src.add_result(
        _record("FOO-004"), source="console", model_label="Foo-Model-7B (recorded)", run_id=run
    )
    src.add_event(
        run, 0, {"type": "step", "req_id": "FOO-004", "node": "prepare", "ok": True, "line": "x", "ts": 1.0}
    )
    src.add_event(
        run, 1, {"type": "result", "req_id": "FOO-004", "status": "passed", "result_id": rid, "ts": 2.0}
    )
    src.update_run(run, status="done", started_at=1.0, finished_at=2.0)
    recorded = tmp_path / "run.json"
    recorded.write_text(json.dumps(src.export_run(run)))

    out = tmp_path / "site"
    cfg = ConsoleConfig(graph=graph, db=tmp_path / "demo.db", artifacts=tmp_path)
    ConsoleDb(cfg.db).set_settings({"llm": {"base_url": "http://gpu-7:8080"}, "llm_api_key": "s3cret"})
    summary = export_demo(cfg, [recorded], out, sizing=False)
    data = out / "data"
    assert summary["files"] > 10
    assert 'data-oge-demo="data/"' in (out / "index.html").read_text()
    assert (out / "static" / "js" / "demo.js").exists()
    run_file = json.loads((data / "runs" / "1.json").read_text())
    [result_event] = [e for e in run_file["events"] if e["type"] == "result"]
    assert result_event["result_id"] == run_file["results"][0]["id"]  # remapped to the demo database
    assert json.loads((data / "status.json").read_text())["workspace"]["ready"] is False
    searches = json.loads((data / "search.json").read_text())
    for hits in searches.values():
        for h in hits:
            assert (data / "nodes" / node_file(h["id"])).exists()
    exported = "".join(p.read_text() for p in data.glob("*.json"))
    assert "s3cret" not in exported
    assert "gpu-7" not in exported  # the exporting site's model server stays private
    # the front end must ask for exactly what was exported
    js = (out / "static" / "js" / "pages" / "search.js").read_text()
    assert all(f'"{q}"' in js for q in SEARCH_EXAMPLES)
    sizing_js = (out / "static" / "js" / "pages" / "sizing.js").read_text()
    assert f"const DEMO_ENGINEERS = [{', '.join(map(str, DEMO_ENGINEERS))}];" in sizing_js
