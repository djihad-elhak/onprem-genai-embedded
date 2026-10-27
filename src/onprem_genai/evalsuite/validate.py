"""Validate the suite itself: references must pass, trivial stubs must fail, every mutant must be killable."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from onprem_genai.evalsuite.scoring import score, score_testgen
from onprem_genai.evalsuite.tasks import Category, Task

_PROTO = re.compile(r"^([A-Za-z_][\w\s\*]*?)\b([A-Za-z_]\w*)\s*\(([^;{]*)\)\s*;", re.MULTILINE)


def stub_solution(header: str) -> str:
    """A compilable solution where every function returns zero / does nothing (must fail the hidden tests)."""
    body = re.sub(r"/\*.*?\*/|//[^\n]*", " ", header, flags=re.DOTALL)
    funcs = []
    for m in _PROTO.finditer(body):
        ret, name, params = m.group(1).strip(), m.group(2), m.group(3).strip()
        if ret.startswith(("typedef", "#")) or name in {"if", "while", "for", "switch", "return"}:
            continue
        # name every parameter so the stub compiles: append a dummy name when only a type is given
        named = []
        for i, p in enumerate(x.strip() for x in params.split(",") if x.strip() and x.strip() != "void"):
            named.append(
                p
                if re.search(r"[A-Za-z_]\w*\s*(\[[^\]]*\])?$", p.split("*")[-1].strip())
                and len(p.replace("*", " ").split()) > 1
                else f"{p} arg{i}"
            )
        sig = f"{ret} {name}({', '.join(named) or 'void'})"
        param_names = [re.split(r"[\s*]+", n.split("[")[0].strip())[-1] for n in named]
        unused = "".join(f"    (void){p};\n" for p in param_names)
        ret_stmt = "" if ret == "void" else f"    return ({ret})0;\n"
        funcs.append(f"{sig}\n{{\n{unused}{ret_stmt}}}\n")
    return '#include "task.h"\n\n' + "\n".join(funcs)


@dataclass
class TaskValidation:
    task: str
    category: str
    ok: bool
    problems: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def validate_task(task: Task) -> TaskValidation:
    v = TaskValidation(task.id, task.category.value, True)
    if task.category is Category.TESTGEN:
        ref = score_testgen(task, task.source("ref_tests.c"))
        v.details = ref.metrics
        if not ref.metrics["tests_pass_on_reference"]:
            v.problems.append("reference tests fail on the reference implementation")
        if ref.metrics["mutants"] < 3:
            v.problems.append("fewer than 3 mutants")
        if ref.metrics["mutation_score"] < 1.0:
            v.problems.append(
                f"reference tests kill only {ref.metrics['mutants_killed']}/{ref.metrics['mutants']}"
            )
    else:
        ref_name = "solution.c"
        ref = score(task, task.source(ref_name))
        v.details = ref.metrics
        if not ref.passed:
            v.problems.append(f"reference does not pass: {ref.metrics} {ref.logs}")
        if task.category is Category.GENERATE and not ref.metrics.get("sanitizer_clean"):
            v.problems.append("reference not sanitizer-clean")
        if task.category is Category.GENERATE:
            stub = score(task, stub_solution(task.header))
            v.details["stub_compiled"] = stub.metrics["compiled"]
            if not stub.metrics["compiled"]:
                v.problems.append(f"stub does not compile: {stub.logs.get('compile', '')[:300]}")
            elif stub.metrics["tests_passed"]:
                v.problems.append("hidden tests pass on an all-zero stub")
        if task.category in (Category.REFACTOR, Category.DOCUMENT):
            orig = score(task, task.source("original.c"))
            v.details["original"] = orig.metrics
            if not orig.metrics["tests_passed"]:
                v.problems.append("original code fails its hidden tests")
            if orig.passed:
                v.problems.append("original already counts as a pass (task is trivial)")
    v.ok = not v.problems
    return v
