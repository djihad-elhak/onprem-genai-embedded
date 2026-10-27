"""Compile, run and score model outputs for each task category. Pure functions over source text."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from onprem_genai.evalsuite.tasks import Category, Task, include_dir

CFLAGS = ["-std=c99", "-Wall", "-Wextra", "-Wpedantic", "-O1"]
SANITIZE = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-sanitize-recover=all", "-g"]
RUN_TIMEOUT_S = 10
COMPILE_TIMEOUT_S = 60


# ------------------------------------------------------------------------------------------- build & run
@dataclass
class BuildRun:
    compiled: bool
    warnings: int
    compile_log: str
    ran: bool = False
    exit_code: int | None = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""

    @property
    def passed(self) -> bool:
        return self.compiled and self.ran and self.exit_code == 0 and not self.timed_out


def build_and_run(
    files: dict[str, str],
    sources: list[str],
    workdir: Path,
    flags: list[str] | None = None,
    run: bool = True,
    env: dict[str, str] | None = None,
) -> BuildRun:
    workdir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (workdir / name).write_text(text, encoding="utf-8")
    exe = workdir / "a.out"
    cmd = [
        "gcc",
        *CFLAGS,
        *(flags or []),
        f"-I{workdir}",
        f"-I{include_dir()}",
        *[str(workdir / s) for s in sources],
        "-o",
        str(exe),
        "-lm",
    ]
    try:
        comp = subprocess.run(cmd, capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return BuildRun(False, 0, "compile timeout")
    log = comp.stderr[-4000:]
    res = BuildRun(comp.returncode == 0, len(re.findall(r"warning:", comp.stderr)), log)
    if not res.compiled or not run:
        return res
    try:
        p = subprocess.run(
            [str(exe)],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            cwd=workdir,
            env=env,
            check=False,
        )
        res.ran, res.exit_code, res.stdout, res.stderr = (
            True,
            p.returncode,
            p.stdout[-2000:],
            p.stderr[-2000:],
        )
    except subprocess.TimeoutExpired:
        res.ran, res.timed_out = True, True
    return res


# ------------------------------------------------------------------------------------------- source analysis
_COMMENT_OR_STRING = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.DOTALL)


def strip_comments(code: str) -> str:
    """Remove C comments while keeping string and character literals intact."""
    return _COMMENT_OR_STRING.sub(lambda m: m.group(0) if m.group(0)[0] in "\"'" else " ", code)


def code_tokens(code: str) -> list[str]:
    return re.findall(r"[A-Za-z_]\w*|\d[\w.]*|\S", strip_comments(code))


def banned_calls(code: str, banned: list[str]) -> list[str]:
    body = strip_comments(code)
    return sorted({b for b in banned if re.search(rf"\b{re.escape(b)}\s*\(", body)})


def has_goto(code: str) -> bool:
    return bool(re.search(r"\bgoto\b", strip_comments(code)))


def complexity(code: str) -> dict[str, float]:
    import lizard  # noqa: PLC0415  (optional dependency: extra 'eval')

    funcs = lizard.analyze_file.analyze_source_code("x.c", code).function_list
    if not funcs:
        return {"functions": 0, "max_ccn": 0, "avg_ccn": 0.0, "max_nloc": 0, "nloc": 0}
    return {
        "functions": len(funcs),
        "max_ccn": max(f.cyclomatic_complexity for f in funcs),
        "avg_ccn": round(sum(f.cyclomatic_complexity for f in funcs) / len(funcs), 2),
        "max_nloc": max(f.nloc for f in funcs),
        "nloc": sum(f.nloc for f in funcs),
    }


_DOC_BLOCK_END = re.compile(r"\*/\s*$")


def _doc_before(lines: list[str], start_line: int) -> str:
    """Doxygen block (``/** ... */`` or ``///`` lines) immediately above a function (1-based start line)."""
    i = start_line - 2
    while i >= 0 and not lines[i].strip():
        i -= 1
    if i < 0:
        return ""
    if lines[i].strip().startswith("///"):
        block = []
        while i >= 0 and lines[i].strip().startswith("///"):
            block.append(lines[i])
            i -= 1
        return "\n".join(reversed(block))
    if _DOC_BLOCK_END.search(lines[i]):
        end = i
        while i >= 0 and "/**" not in lines[i] and "/*!" not in lines[i]:
            i -= 1
        return "\n".join(lines[i : end + 1]) if i >= 0 else ""
    return ""


def documentation_report(code: str) -> dict[str, Any]:
    """Per function: Doxygen brief, every parameter, and the return value (non-void) must be documented."""
    import lizard  # noqa: PLC0415

    lines = code.splitlines()
    required = present = 0
    functions = []
    for f in lizard.analyze_file.analyze_source_code("x.c", code).function_list:
        doc = _doc_before(lines, f.start_line)
        head = lines[f.start_line - 1]
        returns_void = bool(re.search(rf"\bvoid\s*\**\s*\b{re.escape(f.name)}\s*\(", head))
        missing = []
        checks = {"brief": bool(re.search(r"[@\\]brief\s+\S", doc))}
        for p in f.parameters:
            checks[f"param:{p}"] = bool(re.search(rf"[@\\]param(?:\[[a-z, ]+\])?\s+{re.escape(p)}\b", doc))
        if not returns_void:
            checks["return"] = bool(re.search(r"[@\\]returns?\s+\S", doc))
        for k, ok in checks.items():
            required += 1
            present += ok
            if not ok:
                missing.append(k)
        functions.append({"function": f.name, "missing": missing})
    return {"completeness": round(present / required, 4) if required else 0.0, "functions": functions}


# ------------------------------------------------------------------------------------------- scorers
@dataclass
class Score:
    task: str
    category: str
    passed: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    logs: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="oge-eval-"))


def score_generate(task: Task, code: str) -> Score:
    wd = _workdir()
    try:
        files = {"task.h": task.header, "solution.c": code, "tests.c": task.source("tests.c")}
        run = build_and_run(files, ["solution.c", "tests.c"], wd / "plain")
        san = build_and_run(files, ["solution.c", "tests.c"], wd / "san", SANITIZE) if run.passed else None
        violations = banned_calls(code, task.banned)
        m = {
            "compiled": run.compiled,
            "tests_passed": run.passed,
            "warnings": run.warnings,
            "sanitizer_clean": bool(san and san.passed),
            "violations": violations,
        }
        return Score(
            task.id,
            task.category.value,
            run.passed and not violations,
            m,
            {"compile": run.compile_log, "run": run.stderr},
        )
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def _gcov(wd: Path, source: str) -> dict[str, float]:
    """Line / branch coverage of ``source`` from the .gcda produced by a ``--coverage`` run."""
    stem = Path(source).stem
    gcdas = sorted(wd.glob(f"*{stem}.gcda"))
    if not gcdas:
        return {}
    p = subprocess.run(
        ["gcov", "-b", "-n", gcdas[0].name], capture_output=True, text=True, cwd=wd, check=False
    )
    section = p.stdout.split(f"{source}'", 1)
    if len(section) < 2:
        return {}
    body = section[1].split("File '", 1)[0]
    out: dict[str, float] = {}
    if m := re.search(r"Lines executed:([\d.]+)% of (\d+)", body):
        out["line_coverage"] = round(float(m.group(1)) / 100, 4)
    if m := re.search(r"Taken at least once:([\d.]+)% of (\d+)", body):
        out["branch_coverage"] = round(float(m.group(1)) / 100, 4)
    return out


def score_testgen(task: Task, tests: str) -> Score:
    wd = _workdir()
    try:
        files = {"task.h": task.header, "impl.c": task.source("impl.c"), "tests.c": tests}
        ref = build_and_run(files, ["impl.c", "tests.c"], wd / "cov", ["--coverage", "-O0"])
        cov = _gcov(wd / "cov", "impl.c") if ref.passed else {}
        killed = 0
        mutants = task.mutants
        for mpath in mutants:
            mfiles = {"task.h": task.header, "impl.c": mpath.read_text(encoding="utf-8"), "tests.c": tests}
            mr = build_and_run(mfiles, ["impl.c", "tests.c"], wd / f"mut_{mpath.stem}")
            killed += (not mr.compiled) or (not mr.passed)
        n_checks = len(re.findall(r"\bCHECK(?:_EQ_[UI]|_MEM)?\s*\(", strip_comments(tests)))
        m = {
            "compiled": ref.compiled,
            "tests_pass_on_reference": ref.passed,
            "checks": n_checks,
            "line_coverage": cov.get("line_coverage", 0.0),
            "branch_coverage": cov.get("branch_coverage", 0.0),
            "mutants": len(mutants),
            "mutants_killed": killed if ref.passed else 0,
            "mutation_score": round(killed / len(mutants), 4) if (mutants and ref.passed) else 0.0,
        }
        # pass = a valid test program (passes on the correct implementation) that detects every seeded fault
        passed = ref.passed and n_checks > 0 and bool(mutants) and killed == len(mutants)
        return Score(task.id, task.category.value, passed, m, {"compile": ref.compile_log, "run": ref.stderr})
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def score_refactor(task: Task, code: str) -> Score:
    wd = _workdir()
    try:
        files = {"task.h": task.header, "solution.c": code, "tests.c": task.source("tests.c")}
        run = build_and_run(files, ["solution.c", "tests.c"], wd)
        before, after = complexity(task.source("original.c")), complexity(code)
        violations = banned_calls(code, task.banned) + (["goto"] if has_goto(code) else [])
        improved = run.passed and after["max_ccn"] < before["max_ccn"] and not violations
        m = {
            "compiled": run.compiled,
            "tests_passed": run.passed,
            "warnings": run.warnings,
            "violations": violations,
            "ccn_max_before": before["max_ccn"],
            "ccn_max_after": after["max_ccn"],
            "ccn_avg_before": before["avg_ccn"],
            "ccn_avg_after": after["avg_ccn"],
            "functions_after": after["functions"],
            "improved": improved,
        }
        return Score(
            task.id, task.category.value, improved, m, {"compile": run.compile_log, "run": run.stderr}
        )
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def score_document(task: Task, code: str) -> Score:
    wd = _workdir()
    try:
        files = {"task.h": task.header, "solution.c": code, "tests.c": task.source("tests.c")}
        run = build_and_run(files, ["solution.c", "tests.c"], wd)
        unchanged = code_tokens(code) == code_tokens(task.source("original.c"))
        doc = documentation_report(code)
        m = {
            "compiled": run.compiled,
            "tests_passed": run.passed,
            "code_unchanged": unchanged,
            "doc_completeness": doc["completeness"],
            "missing": [f for f in doc["functions"] if f["missing"]],
        }
        passed = run.passed and unchanged and doc["completeness"] == 1.0
        return Score(task.id, task.category.value, passed, m, {"compile": run.compile_log})
    finally:
        shutil.rmtree(wd, ignore_errors=True)


SCORERS = {
    Category.GENERATE: score_generate,
    Category.TESTGEN: score_testgen,
    Category.REFACTOR: score_refactor,
    Category.DOCUMENT: score_document,
}


def score(task: Task, output: str) -> Score:
    return SCORERS[task.category](task, output)


def reference_output(task: Task) -> str:
    """The reference answer used to validate a task's harness."""
    return task.source("ref_tests.c" if task.category is Category.TESTGEN else "solution.c")
