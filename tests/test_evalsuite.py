"""Evaluation suite: task validity, scoring, code extraction, runner and reporting."""

from __future__ import annotations

import json
import shutil

import httpx
import pytest

from onprem_genai.evalsuite import prompts, runner
from onprem_genai.evalsuite.scoring import (
    code_tokens,
    documentation_report,
    reference_output,
    score,
    strip_comments,
)
from onprem_genai.evalsuite.tasks import Category, load_tasks
from onprem_genai.evalsuite.validate import stub_solution, validate_task

pytestmark = pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc not available")

TASKS = load_tasks()
BY_ID = {t.id: t for t in TASKS}
ONE_PER_CATEGORY = ["gen-crc16-ccitt", "tst-tick-elapsed", "ref-frame-parser", "doc-pid"]


def test_suite_shape() -> None:
    counts = {c: sum(t.category is c for t in TASKS) for c in Category}
    assert counts == {Category.GENERATE: 12, Category.TESTGEN: 6, Category.REFACTOR: 5, Category.DOCUMENT: 4}
    assert all(len(t.mutants) >= 3 for t in TASKS if t.category is Category.TESTGEN)


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_every_task_is_valid(task) -> None:
    v = validate_task(task)
    assert v.ok, v.problems


def test_stub_solution_compiles_signatures() -> None:
    stub = stub_solution(BY_ID["gen-ring-buffer"].header)
    assert "bool rb_push(" in stub
    assert "return (bool)0;" in stub


def test_strip_comments_keeps_literals() -> None:
    code = 'int a = 1; /* x */ const char *s = "/* not a comment */"; // y\n'
    stripped = strip_comments(code)
    assert '"/* not a comment */"' in stripped
    assert "x */" not in stripped
    assert "// y" not in stripped


def test_document_scoring_rejects_code_changes() -> None:
    task = BY_ID["doc-pid"]
    documented = reference_output(task)
    assert score(task, documented).passed
    tampered = documented.replace("/ 256", "/ 128")
    s = score(task, tampered)
    assert not s.passed
    assert not s.metrics["code_unchanged"]
    assert code_tokens(documented) != code_tokens(tampered)


def test_documentation_report_counts_params_and_return() -> None:
    code = "/**\n * @brief Add.\n * @param a first\n */\nint add(int a, int b)\n{\n    return a + b;\n}\n"
    rep = documentation_report(code)
    assert rep["completeness"] == pytest.approx(2 / 4)
    assert set(rep["functions"][0]["missing"]) == {"param:b", "return"}


def test_refactor_rejects_goto_and_unchanged_code() -> None:
    task = BY_ID["ref-frame-parser"]
    s = score(task, task.source("original.c"))
    assert s.metrics["tests_passed"]
    assert not s.passed
    assert "goto" in s.metrics["violations"]


def test_testgen_requires_killing_all_mutants() -> None:
    task = BY_ID["tst-tick-elapsed"]
    weak = (
        '#include "task.h"\n#include "oge_test.h"\nint main(void)\n{\n    CHECK(tick_elapsed(2u, 1u, 1u));\n'
        "    return OGE_REPORT();\n}\n"
    )
    s = score(task, weak)
    assert s.metrics["tests_pass_on_reference"]
    assert s.metrics["mutation_score"] < 1.0
    assert not s.passed


# ------------------------------------------------------------------------------------------- prompts
def test_prompts_contain_inputs_but_never_hidden_material() -> None:
    for task in TASKS:
        user = prompts.build_messages(task)[1]["content"]
        assert task.header.strip() in user
        hidden = ["tests.c", "solution.c", "ref_tests.c"]
        for name in hidden:
            path = task.root / name
            if path.exists():
                body = path.read_text().strip()
                assert body not in user, f"{task.id}: {name} leaked into the prompt"
        if task.category is Category.TESTGEN:
            assert task.source("impl.c").strip() in user
            for m in task.mutants:
                assert m.read_text().strip() not in user


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("```c\nint x;\n```", "int x;\n"),
        ("<think>try ```c\nwrong\n```</think>\nFinal:\n```c\nint good;\n```", "int good;\n"),
        ("reasoning...</think>\n```c\nint after_close;\n```", "int after_close;\n"),
        ("```text\nnote\n```\n```c\nint a;\nint b;\n```", "int a;\nint b;\n"),
        ("```\nint plain;\n```", "int plain;\n"),
        ("int no_fence;", "int no_fence;\n"),
        ("```c\nint cut_by_max_tokens;", "int cut_by_max_tokens;\n"),
    ],
)
def test_extract_code(answer: str, expected: str) -> None:
    assert prompts.extract_code(answer) == expected


# ------------------------------------------------------------------------------------------- runner
def test_pass_at_k() -> None:
    assert runner.pass_at_k(5, 0, 1) == 0.0
    assert runner.pass_at_k(5, 5, 1) == 1.0
    assert runner.pass_at_k(4, 1, 1) == pytest.approx(0.25)
    assert runner.pass_at_k(4, 1, 2) == pytest.approx(0.5)


def test_reference_oracle_scores_100_percent() -> None:
    tasks = [BY_ID[i] for i in ONE_PER_CATEGORY]
    results = runner.run_suite(tasks, runner.reference_generator, concurrency=4)
    summary = runner.summarize(results, samples=1)
    assert summary["overall_pass@1"] == 1.0
    assert set(summary["categories"]) == {"generate", "testgen", "refactor", "document"}


def test_chat_client_end_to_end_with_resume(tmp_path) -> None:
    """Mock server: right answer for one task, wrong for another, a 503 retried, auth + extra body."""
    calls: list[dict] = []
    flaky = {"left": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer k"
        body = json.loads(request.content)
        calls.append(body)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        user = body["messages"][1]["content"]
        if "Unit tests for wraparound-safe timeouts" in user and flaky["left"]:
            flaky["left"] -= 1
            return httpx.Response(503, json={"error": "busy"})
        if "CRC-16" in user or "crc16" in user:
            text = f"```c\n{reference_output(BY_ID['gen-crc16-ccitt'])}```"
        else:
            text = '```c\n#include "task.h"\n```'
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    client = runner.ChatClient(
        "http://mock",
        "m",
        api_key="k",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        backoff_s=0.0,
        transport=httpx.MockTransport(handler),
    )
    tasks = [BY_ID["gen-crc16-ccitt"], BY_ID["tst-tick-elapsed"]]
    partial = tmp_path / "r.partial.jsonl"
    results = runner.run_suite(tasks, client, samples=2, concurrency=2, partial_path=partial)
    assert [(r.task, r.passed) for r in results] == [
        ("gen-crc16-ccitt", True),
        ("gen-crc16-ccitt", True),
        ("tst-tick-elapsed", False),
        ("tst-tick-elapsed", False),
    ]
    assert all(r.error is None and r.completion_tokens == 50 for r in results)
    assert len(calls) == 5  # 4 jobs + 1 retried 503

    # resume: every job is already in the partial file, so no new request is sent
    again = runner.run_suite(tasks, client, samples=2, concurrency=2, partial_path=partial)
    assert len(calls) == 5
    assert [r.passed for r in again] == [r.passed for r in results]

    report = runner.build_report(results, 2, {"model": "m", "label": "mock"})
    cats = report["summary"]["categories"]
    assert cats["generate"]["pass@1"] == 1.0
    assert cats["testgen"]["pass@1"] == 0.0
    assert cats["testgen"]["valid_rate"] == 0.0
    table = runner.markdown_table([report])
    assert "| mock | 100% | 0% (0%)" in table


def test_request_failure_is_a_failed_sample() -> None:
    def boom(task, messages):
        raise RuntimeError("connection refused")

    [r] = runner.run_suite([BY_ID["gen-crc32"]], boom)
    assert not r.passed
    assert "connection refused" in (r.error or "")
    assert runner.summarize([r], 1)["request_errors"] == 1
