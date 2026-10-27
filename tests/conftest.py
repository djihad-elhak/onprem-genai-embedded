from __future__ import annotations

import os
from pathlib import Path

import pytest

from onprem_genai.knowledge.fprime.ingest import ingest_fprime
from onprem_genai.knowledge.model import Graph

SDD = """# Svc::Foo

## 1 Introduction
Foo dispatches commands and drops them when its queue is full.

## 2 Requirements

| Requirement | Description | Verification Method |
|---|---|---|
| FOO-001 | The Svc::Foo component shall dispatch commands to registered handlers. | Unit Test |
| FOO-002 | The Svc::Foo component shall drop commands when the queue is full. | Unit Test |
| FOO-003 | The Svc::Foo component shall report its version. | Inspection |
| FOO-004 | The Svc::Foo component shall emit telemetry for the dispatch count. | Unit Test |

## 3 Design
Commands arrive on cmdIn and are dispatched by doDispatch.
"""

FOO_CPP = """
#include "Svc/Foo/Foo.hpp"
namespace Svc {
/// Dispatches one command to its handler.
void Foo::doDispatch(U32 opcode) {
    lookupHandler(opcode);
}
void Foo::lookupHandler(U32 opcode) {
}
void Foo::cmdIn_handler(FwIndexType port, U32 opcode) {
    if (queueFull()) { dropCommand(opcode); return; }
    doDispatch(opcode);
}
bool Foo::queueFull() { return false; }
void Foo::dropCommand(U32 opcode) { }
void Foo::DUMP_cmdHandler(FwOpcodeType op, U32 seq) { }
}
"""

TESTER_CPP = """
#include "Svc/Foo/test/ut/FooTester.hpp"
namespace Svc {
void FooTester::runNominalDispatch() {
    REQUIREMENT("FOO-001");
    this->invoke_to_cmdIn(0, 1);
}
void FooTester::runQueueFullDrop() {
    REQUIREMENT("FOO-002");
    // fill the queue then check the command is dropped
    this->invoke_to_cmdIn(0, 2);
}
void FooTester::runDump() {
    this->sendCmd_DUMP(0, 10);
}
void FooTester::runOtherModuleTag() {
    REQUIREMENT("BAR-001");
}
}
TEST(Nominal, Dispatch) {
    Svc::FooTester tester;
    tester.runNominalDispatch();
}
"""


def make_mini_fprime(root: Path) -> Path:
    foo = root / "Svc" / "Foo"
    (foo / "docs").mkdir(parents=True)
    (foo / "test" / "ut").mkdir(parents=True)
    (foo / "CMakeLists.txt").write_text("register_fprime_module()\n")
    (foo / "Foo.cpp").write_text(FOO_CPP)
    (foo / "docs" / "sdd.md").write_text(SDD)
    (foo / "test" / "ut" / "FooTester.cpp").write_text(TESTER_CPP)
    bar = root / "Svc" / "Bar"
    (bar / "docs").mkdir(parents=True)
    (bar / "CMakeLists.txt").write_text("register_fprime_module()\n")
    (bar / "Bar.cpp").write_text("namespace Svc { void Bar::run() { } }\n")
    (bar / "docs" / "sdd.md").write_text(
        "| Requirement | Description | Verification Method |\n|---|---|---|\n"
        "| BAR-001 | The Svc::Bar component shall run. | Unit Test |\n"
    )
    return root


@pytest.fixture(scope="session")
def mini_graph(tmp_path_factory: pytest.TempPathFactory) -> Graph:
    root = make_mini_fprime(tmp_path_factory.mktemp("fprime"))
    g, _ = ingest_fprime(root, top_dirs=("Svc",))
    return g


def neo4j_settings() -> tuple[str, str, str] | None:
    uri = os.environ.get("NEO4J_URI")
    if not uri:
        return None
    return uri, os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")
