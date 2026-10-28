"""Test-generation agent: parsing, policy, patching, diagnostics, mutation operators, bookkeeping.

The end-to-end run on real F´ (LangGraph graph + MCP + fprime-util build + gtest + git) is
``test_agent_e2e``, marked ``fprime``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from onprem_genai.agent import context as ctxmod
from onprem_genai.agent import mutation
from onprem_genai.agent.fprime import FprimeWorkspace, condense_diagnostics, find_component
from onprem_genai.agent.patch import PatchError, build_patch, parse_answer, render
from onprem_genai.agent.runner import ScriptedModel, review_sheet, summarize

HPP = """\
#ifndef FOO_TESTER_HPP
#define FOO_TESTER_HPP
#include "FooGTestBase.hpp"
namespace Svc {
class FooTester final : public FooGTestBase {
  public:
    FooTester();
    void testDispatch();
  private:
    void connectPorts();
    Foo component;
};
}  // namespace Svc
#endif
"""
CPP = """\
#include "FooTester.hpp"
namespace Svc {
FooTester::FooTester() : FooGTestBase("Tester", 10), component("Foo") {}
void FooTester::testDispatch() {
    this->invoke_to_cmdIn(0, 1);
    ASSERT_from_dataOut_SIZE(1);
}
void FooTester::connectPorts() {}
}  // namespace Svc
"""
MAIN = """\
#include "FooTester.hpp"
TEST(Nominal, Dispatch) {
    Svc::FooTester tester;
    tester.testDispatch();
}
int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
"""
IMPL = """\
#include "Foo.hpp"
namespace Svc {
void Foo::cmdIn_handler(FwIndexType portNum, U32 opcode) {
    if (opcode == 0 && this->m_enabled) {
        return;
    }
    this->dataOut_out(0, opcode + 1);
    this->log_ACTIVITY_LO_Dispatched(opcode);
}
}
"""


def good_answer(req: str = "FOO-002", tag: bool = True) -> str:
    tag_line = f'    REQUIREMENT("{req}");\n' if tag else ""
    return (
        "Reasoning.\n```cpp tester\n#include <cstring>\n"
        "void FooTester::testDropWhenFull() {\n" + tag_line + "    this->clearHistory();\n"
        "    this->invoke_to_cmdIn(0, 0);\n    ASSERT_from_dataOut_SIZE(0);\n}\n"
        "void FooTester::fillQueue(U32 n) {\n    (void)n;\n}\n```\n"
        "```cpp main\nTEST(Requirement, DropWhenFull) {\n    Svc::FooTester tester;\n"
        "    tester.testDropWhenFull();\n}\n```\n"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    comp = tmp_path / "Svc" / "Foo"
    ut = comp / "test" / "ut"
    ut.mkdir(parents=True)
    (ut / "FooTester.hpp").write_text(HPP)
    (ut / "FooTester.cpp").write_text(CPP)
    (ut / "FooTestMain.cpp").write_text(MAIN)
    (comp / "Foo.cpp").write_text(IMPL)
    (comp / "Foo.hpp").write_text("class Foo { bool m_enabled; static const U32 QUEUE_DEPTH = 4; };\n")
    (comp / "Foo.fpp").write_text("module Svc { passive component Foo { sync input port cmdIn: CmdPort } }\n")
    auto = tmp_path / "build-fprime-automatic-native-ut" / "F-Prime" / "Svc" / "Foo"
    auto.mkdir(parents=True)
    (auto / "FooGTestBase.hpp").write_text(
        "#define ASSERT_from_dataOut_SIZE(size) \\\n  this->assert_from_dataOut_size(size)\n"
        "#define ASSERT_EVENTS_Dispatched(index, _opcode) \\\n  this->x(index)\n"
    )
    (auto / "FooTesterBase.hpp").write_text(
        "class FooTesterBase {\n  protected:\n    //! Invoke cmdIn\n"
        "    void invoke_to_cmdIn(\n        FwIndexType portNum, //!< port\n        U32 opcode\n    );\n"
        "    static void from_dataOut_static(Fw::PassiveComponentBase* const c, FwIndexType portNum);\n"
        "};\n"
    )
    return tmp_path


# ------------------------------------------------------------------------------------------- parsing & policy
def test_find_component(repo: Path) -> None:
    c = find_component(repo, "module:Svc/Foo")
    assert (c.tester_class, c.name, c.target) == ("FooTester", "Foo", "Svc_Foo")
    assert c.test_main.name == "FooTestMain.cpp"
    assert [p.name for p in c.impl_sources] == ["Foo.cpp"]


def test_parse_answer_variants() -> None:
    a = parse_answer(good_answer())
    assert "testDropWhenFull" in a.tester_code
    assert "TEST(Requirement" in a.main_code
    unlabeled = good_answer().replace("```cpp tester", "```cpp").replace("```cpp main", "```cpp")
    b = parse_answer(unlabeled)
    assert "TEST(" in b.main_code
    assert "TEST(" not in b.tester_code
    assert parse_answer("<think>maybe</think>NOT_TESTABLE: verified by inspection").not_testable == (
        "verified by inspection"
    )


def test_build_patch_derives_declarations_and_names(repo: Path) -> None:
    c = find_component(repo, "Svc/Foo")
    p = build_patch(parse_answer(good_answer()), c, "FOO-002")
    assert p.method_names == ["testDropWhenFull", "fillQueue"]
    assert [d.declaration for d in p.definitions] == ["void testDropWhenFull();", "void fillQueue(U32 n);"]
    assert p.test_names == ["Requirement.DropWhenFull"]
    assert p.includes == ["#include <cstring>"]


def test_requirement_tag_is_enforced(repo: Path) -> None:
    c = find_component(repo, "Svc/Foo")
    p = build_patch(parse_answer(good_answer(tag=False)), c, "FOO-002")
    assert 'REQUIREMENT("FOO-002");' in p.definitions[0].text
    with pytest.raises(PatchError, match="only REQUIREMENT"):
        build_patch(parse_answer(good_answer("FOO-001")), c, "FOO-002")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda a: a.replace("void FooTester::fillQueue", "static void fillQueue"),
            "not members of FooTester",
        ),
        (lambda a: a.replace("testDropWhenFull", "testDispatch"), "already defines"),
        (
            lambda a: a.replace("DropWhenFull)", "Dispatch)").replace("Requirement,", "Nominal,"),
            "already exist",
        ),
        (lambda a: a.replace("ASSERT_from_dataOut_SIZE(0);", 'system("rm -rf /");'), "system"),
        (lambda a: a.replace("ASSERT_from_dataOut_SIZE(0);", "(void)0;"), "no assertion"),
        (lambda a: a.replace("tester.testDropWhenFull();", ""), "must call one of the new"),
        (lambda a: a.replace("TEST(Requirement", "TEST_F(Requirement"), "plain gtest TEST"),
        (lambda a: a.split("```cpp main")[0], "missing the ```cpp main```"),
        (lambda a: a.replace("this->clearHistory();", "#define private public"), "preprocessor"),
    ],
)
def test_policy_rejections(repo: Path, mutate, message: str) -> None:
    c = find_component(repo, "Svc/Foo")
    with pytest.raises(PatchError, match=message):
        build_patch(parse_answer(mutate(good_answer())), c, "FOO-002")


def test_render_inserts_at_structural_anchors(repo: Path) -> None:
    c = find_component(repo, "Svc/Foo")
    p = build_patch(parse_answer(good_answer()), c, "FOO-002")
    out = render(c, p, "FOO-002")
    hpp, cpp, main = out[str(c.tester_hpp)], out[str(c.tester_cpp)], out[str(c.test_main)]
    assert hpp.index("void testDropWhenFull();") < hpp.index("};")  # inside the class
    assert "  public:\n    //! Tests generated for requirement FOO-002" in hpp
    assert cpp.index("void FooTester::testDropWhenFull()") > cpp.index("void FooTester::connectPorts()")
    assert cpp.index("void FooTester::testDropWhenFull()") < cpp.index(
        "}  // namespace Svc"
    )  # same namespace
    assert '#include "Fw/Test/UnitTest.hpp"' in cpp
    assert "#include <cstring>" in cpp
    assert main.index("TEST(Requirement, DropWhenFull)") < main.index("int main(")
    assert hpp.count("class FooTester") == 1


def test_harness_api_and_repair_hints(repo: Path) -> None:
    ws = FprimeWorkspace(repo)
    c = find_component(repo, "Svc/Foo")
    api, names = ctxmod.harness_api(ws, c)
    assert "ASSERT_from_dataOut_SIZE(size)" in api
    assert "void invoke_to_cmdIn(FwIndexType portNum, U32 opcode)" in api
    assert "_static" not in api

    class NoKb:
        async def symbol(self, name: str, module: str | None = None) -> list:
            return []

    ctx = ctxmod.AgentContext("FOO-002", {}, api_names=names, known_names=["QUEUE_DEPTH", "m_enabled"])
    errors = (
        "FooTester.cpp:9:5: error: 'ASSERT_from_dataout_SIZE' was not declared in this scope\n"
        "FooTester.cpp:10:5: error: 'class Svc::Foo' has no member named 'm_enable'\n"
    )
    hints = asyncio.run(ctxmod.repair_hints(errors, ctx, NoKb(), c))  # type: ignore[arg-type]
    assert "ASSERT_from_dataOut_SIZE" in hints
    assert "m_enabled" in hints


def test_context_budget_keeps_priorities() -> None:
    ctx = ctxmod.AgentContext("X-1", {})
    ctx.sections = [
        ctxmod.ContextSection("Requirement", "R" * 100, priority=0),
        ctxmod.ContextSection("Big file", "x" * 5000, "cpp", priority=5),
        ctxmod.ContextSection("Model", "m" * 1000, "fpp", priority=1),
    ]
    text = ctx.render(3500)
    assert text.index("### Requirement") < text.index("### Model") < text.index("### Big file (truncated)")
    assert len(text) <= 3500


def test_condense_diagnostics_relative_paths() -> None:
    log = (
        "[1/3] Building CXX object x.o\n"
        "/repo/Svc/Foo/test/ut/FooTester.cpp:12:5: error: 'ASSERT_x' was not declared in this scope\n"
        "   12 |     ASSERT_x(1);\n      |     ^~~~~~~~\n"
        "/repo/Svc/Foo/test/ut/FooTester.cpp:12:5: error: 'ASSERT_x' was not declared in this scope\n"
        "/usr/bin/ld: FooTester.cpp.o: undefined reference to `Svc::FooTester::helper()'\n"
    )
    out = condense_diagnostics(log, Path("/repo"))
    assert out.startswith("Svc/Foo/test/ut/FooTester.cpp:12:5: error")
    assert out.count("was not declared") == 1
    assert "undefined reference to `Svc::FooTester::helper()'" in out


# ------------------------------------------------------------------------------------ mutation operators
def test_mutation_candidates_and_sampling(repo: Path) -> None:
    impl = repo / "Svc" / "Foo" / "Foo.cpp"
    muts = mutation.candidates(impl, {3, 4, 5, 7, 8})
    ops = {m.operator for m in muts}
    assert {"rel ==→!=", "logic &&→||", "const +1→+0", "delete effect statement"} <= ops
    deleted = [m for m in muts if m.operator == "delete effect statement"]
    assert {m.line for m in deleted} == {7, 8}
    assert all(m.mutated != m.original for m in muts)
    a = mutation.sample(muts, 3, "FOO-002")
    b = mutation.sample(muts, 3, "FOO-002")
    assert [(m.line, m.operator) for m in a] == [(m.line, m.operator) for m in b]
    assert len({m.operator for m in a}) == 3  # spread over operators first


# ------------------------------------------------------------------------------------ runner bookkeeping
def test_scripted_model_replays_in_order() -> None:
    model = ScriptedModel({"R-1": ["first", "second"]})
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "... verifies requirement R-1. ..."},
    ]
    assert [model(msgs).text for _ in range(3)] == ["first", "second", "second"]
    other = [{"role": "user", "content": "verifies requirement R-2."}]
    assert model(other).text.startswith("NOT_TESTABLE")


def test_summary_and_review_sheet() -> None:
    recs = [
        {
            "req_id": "A-1",
            "module": "Svc/A",
            "status": "passed",
            "attempts": 2,
            "wall_seconds": 10.0,
            "metrics": {
                "first_attempt_compiled": False,
                "compiled": True,
                "llm_calls": 2,
                "completion_tokens": 300,
                "coverage_delta": 0.05,
                "test_names": ["R.A1"],
                "mutation": {"valid": 4, "killed": 3, "score": 0.75},
            },
            "history": [],
            "diff": "+ test",
            "commit": "abc1234567",
        },
        {
            "req_id": "A-2",
            "module": "Svc/A",
            "status": "failed",
            "attempts": 3,
            "wall_seconds": 20.0,
            "metrics": {"first_attempt_compiled": True, "compiled": True, "llm_calls": 3},
            "reason": "test",
            "history": [],
        },
        {
            "req_id": "A-3",
            "module": "Svc/A",
            "status": "not_testable",
            "attempts": 1,
            "wall_seconds": 1.0,
            "metrics": {"llm_calls": 1},
            "reason": "inspection",
            "history": [],
        },
    ]
    s = summarize(recs)
    assert s["status"] == {"passed": 1, "failed": 1, "not_testable": 1}
    assert s["verified_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert s["first_attempt_compile_rate"] == 0.5
    assert s["mutation"] == {"tests_analysed": 1, "valid_mutants": 4, "killed": 3, "mean_score": 0.75}
    assert s["per_module"]["Svc/A"] == {"targets": 3, "passed": 1, "coverage_delta": 0.05}
    sheet = review_sheet(recs, "m")
    for expected in ("## A-1 — passed", "3/4 mutants killed", "- reason: inspection"):
        assert expected in sheet


# ------------------------------------------------------------------------------------------- end to end on F´
FPRIME = Path("third_party/fprime")
SCRIPTED = Path(__file__).parent / "data" / "scripted_agent_answers.json"


def _fprime_ready() -> str | None:
    if not (FPRIME / "Svc" / "ComStub").is_dir():
        return "run scripts/fetch_fprime.sh"
    tool = FprimeWorkspace(FPRIME).fprime_util
    if not (Path(tool).exists() or shutil.which(tool)):
        return "F´ tools missing: run scripts/setup_fprime_ut.sh"
    if not (FPRIME / "build-fprime-automatic-native-ut").is_dir():
        return "unit-test build cache missing: run scripts/setup_fprime_ut.sh"
    return None


@pytest.mark.fprime
def test_agent_e2e(tmp_path: Path) -> None:
    """Scripted model, real everything else: MCP retrieval, patching, fprime-util build, gtest, gcov, git."""
    if reason := _fprime_ready():
        pytest.skip(reason)
    from onprem_genai.agent.graph import AgentConfig, AgentDeps  # noqa: PLC0415
    from onprem_genai.agent.knowledge import KnowledgeClient  # noqa: PLC0415
    from onprem_genai.agent.runner import run_batch  # noqa: PLC0415
    from onprem_genai.knowledge.fprime.ingest import ingest_fprime  # noqa: PLC0415
    from onprem_genai.knowledge.store import InMemoryStore  # noqa: PLC0415
    from onprem_genai.mcp_server.server import build_server  # noqa: PLC0415

    g, _ = ingest_fprime(FPRIME, top_dirs=("Svc",))
    answers = {k: v for k, v in json.loads(SCRIPTED.read_text()).items() if not k.startswith("_")}
    ws = FprimeWorkspace(FPRIME)
    if ws.changed_files():
        pytest.skip("F´ checkout has local changes")
    origin = ws.head()
    branch = "oge-agent/pytest-e2e"
    out = tmp_path / "run.jsonl"

    model = ScriptedModel(answers)
    prompt_sizes: list[int] = []

    def llm(messages: list[dict[str, str]]):
        prompt_sizes.append(len(messages))
        return model(messages)

    async def go() -> list[dict]:
        async with KnowledgeClient(build_server(InMemoryStore(g))) as kb:
            deps = AgentDeps(ws, kb, llm, AgentConfig(model_label="scripted", mutants=2))
            return await run_batch(deps, list(answers), out, branch)

    try:
        recs = {r["req_id"]: r for r in asyncio.run(go())}
        stages = {k: [h["stage"] for h in r["history"]] for k, r in recs.items()}
        assert stages == {
            "SVC-COMSTUB-003": ["build", "passed"],
            "SVC-COMSTUB-006": ["test", "passed"],
            "SVC-COMSTUB-007": ["policy", "passed"],
            "SVC-COMSTUB-001": ["not_testable"],
        }
        assert all(recs[r]["status"] == "passed" and recs[r]["commit"] for r in list(answers)[:3])
        assert recs["SVC-COMSTUB-003"]["metrics"]["first_attempt_compiled"] is False
        assert max(prompt_sizes) == 4  # repair prompts: system, task, latest answer, its diagnostics
        assert recs["SVC-COMSTUB-006"]["metrics"]["mutation"]["valid"] >= 1
        log = ws.git("log", "--format=%an|%s", f"{origin}..HEAD")
        assert log.count("oge-agent (scripted)|test(ComStub): verify SVC-COMSTUB-") == 3
        changed = ws.git("diff", "--name-only", f"{origin}..HEAD").split()
        assert sorted(changed) == sorted(
            f"Svc/ComStub/test/ut/{n}"
            for n in ("ComStubTester.hpp", "ComStubTester.cpp", "ComStubTestMain.cpp")
        )
        assert ws.changed_files() == []  # mutation analysis restored the implementation
        tagged = ws.git("grep", "-c", 'REQUIREMENT("SVC-COMSTUB-00', "HEAD", "--", "Svc/ComStub/test/ut")
        assert tagged.strip().endswith(":3")
    finally:
        subprocess.run(["git", "-C", str(FPRIME), "checkout", "-q", "--detach", origin], check=False)
        subprocess.run(["git", "-C", str(FPRIME), "branch", "-D", branch], check=False, capture_output=True)
