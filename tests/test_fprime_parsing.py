from __future__ import annotations

from pathlib import Path

import pytest

from onprem_genai.knowledge.fprime.cpp import parse_cpp
from onprem_genai.knowledge.fprime.ingest import (
    _doc_chunks,
    _fprime_short_name_aliases,
    is_test_path,
    module_of,
)
from onprem_genai.knowledge.fprime.requirements import parse_requirement_tables

SDD = """
# Svc::Foo

## 2 Requirements

Requirement | Description | Rationale | Verification Method
---- | ---- | ---- | ----
FOO-001 | The `Svc::Foo` component shall **dispatch** commands. | Needed | Unit Test
FOO-002 | The component shall drop commands when full. | DoS | Inspection

| Name | Description | Validation |
|---|---|---|
| SVC-Ccsds-FOO-003 | Mixed-case IDs are valid. | Unit Test |

| Port | Description |
|---|---|
| cmdIn | not a requirement table |
"""

CPP = b"""
#include "Svc/Foo/Foo.hpp"
#include <gtest/gtest.h>
namespace Svc {
/// Runs the nominal scenario.
void FooTester::runNominal() {
    REQUIREMENT("FOO-001");
    this->sendCmd_DISPATCH(0, 1);
    this->invoke_to_cmdIn(0, buf);
    helper();
}
class Inline : public Base { public: void inl() { other(); } };
}
TEST(Nominal, Dispatch) {
    Svc::FooTester tester;
    tester.runNominal();
    REQUIREMENT("FOO-002");
}
"""


def test_requirement_tables_content_based() -> None:
    rows = parse_requirement_tables(SDD, "Svc/Foo/docs/sdd.md")
    assert [r.req_id for r in rows] == ["FOO-001", "FOO-002", "SVC-Ccsds-FOO-003"]
    assert rows[0].text == "The Svc::Foo component shall dispatch commands."
    assert rows[0].verification == "Unit Test"
    assert rows[0].rationale == "Needed"
    assert rows[1].verification == "Inspection"
    assert rows[2].verification == "Unit Test"


def test_cpp_functions_calls_tags_and_gtest() -> None:
    info = parse_cpp(CPP)
    assert info.includes == ["Svc/Foo/Foo.hpp", "gtest/gtest.h"]
    by_name = {f.name: f for f in info.functions}
    run = by_name["runNominal"]
    assert run.qualified == "Svc::FooTester::runNominal"
    assert run.class_name == "FooTester"
    assert run.requirement_tags == [("FOO-001", 7)]
    assert "sendCmd_DISPATCH" in run.calls
    assert "helper" in run.calls
    assert "REQUIREMENT" not in run.calls
    assert "Runs the nominal scenario" in run.doc
    inl = by_name["inl"]
    assert inl.class_name == "Inline"
    assert inl.qualified == "Svc::Inline::inl"
    case = by_name["Nominal.Dispatch"]
    assert case.is_gtest_case
    assert case.requirement_tags[0][0] == "FOO-002"
    assert info.classes[0].bases == ["Base"]


def test_fprime_conventions() -> None:
    assert _fprime_short_name_aliases("sendCmd_DISPATCH") == ["sendCmd_DISPATCH", "DISPATCH_cmdHandler"]
    assert _fprime_short_name_aliases("invoke_to_cmdIn") == ["invoke_to_cmdIn", "cmdIn_handler"]
    assert _fprime_short_name_aliases("helper") == ["helper"]


def test_module_resolution(tmp_path: Path) -> None:
    (tmp_path / "Svc" / "Foo" / "test" / "ut").mkdir(parents=True)
    (tmp_path / "Svc" / "Foo" / "CMakeLists.txt").write_text("")
    assert module_of(Path("Svc/Foo/Foo.cpp"), tmp_path) == Path("Svc/Foo")
    assert module_of(Path("Svc/Foo/test/ut/FooTester.cpp"), tmp_path) == Path("Svc/Foo")
    assert is_test_path(Path("Svc/Foo/test/ut/FooTester.cpp"))
    assert not is_test_path(Path("Svc/Foo/Foo.cpp"))


def test_doc_chunks_skip_requirement_sections() -> None:
    chunks = _doc_chunks(SDD + "\n## 3 Design\nThe design text.\n")
    headings = [h for h, _ in chunks]
    assert "3 Design" in headings
    assert all("requirement" not in h.lower() for h in headings)


@pytest.mark.fprime
def test_ingest_pinned_fprime() -> None:
    from onprem_genai.knowledge.fprime.ingest import ingest_fprime  # noqa: PLC0415
    from onprem_genai.knowledge.model import EdgeType, NodeType  # noqa: PLC0415

    root = Path("third_party/fprime")
    if not root.exists():
        pytest.skip("run scripts/fetch_fprime.sh")
    g, report = ingest_fprime(root)
    assert report.requirements >= 500
    assert report.tags_resolved >= 450
    req = "req:CD-001"
    verifying = {n.props["name"] for n in g.predecessors(req, EdgeType.VERIFIES)}
    assert "runNominalDispatch" in verifying
    assert g.successors(req, EdgeType.ALLOCATED_TO)[0].id == "module:Svc/CmdDispatcher"
    assert any("ISF-HTH-001" in u for u in report.tags_to_undefined_requirement)
    assert len(g.of_type(NodeType.TEST_CASE)) > 1000
