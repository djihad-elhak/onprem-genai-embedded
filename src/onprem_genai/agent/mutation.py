"""Fault-detection check of a generated test: does it fail when the code it exercises is broken?

Mutants are generated only on implementation lines that the new test executes (gcov), with operators that
model typical flight-software faults: inverted conditions, off-by-one bounds, swapped success / failure
statuses, and dropped port calls, events or telemetry writes. A mutant that does not compile is discarded; a
valid mutant is killed when the new test fails on it. The implementation file is always restored.

This is an evaluation of the agent's output, not something the agent sees or can optimise against.
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from onprem_genai.agent.fprime import Component, FprimeWorkspace

# (operator name, pattern, replacement) — applied at one match position at a time
OPERATORS: list[tuple[str, str, str]] = [
    ("rel ==→!=", r"(?<![=!<>])==(?!=)", "!="),
    ("rel !=→==", r"!=", "=="),
    ("rel <=→<", r"<=", "<"),
    ("rel >=→>", r">=", ">"),
    ("rel <→<=", r"(?<![<\-])<(?![<=])(?=\s)", "<="),
    ("rel >→>=", r"(?<![>\-])>(?![>=])(?=\s)", ">="),
    ("logic &&→||", r"&&", "||"),
    ("logic ||→&&", r"\|\|", "&&"),
    ("bool true→false", r"\btrue\b", "false"),
    ("bool false→true", r"\bfalse\b", "true"),
    ("status SUCCESS→FAILURE", r"::SUCCESS\b", "::FAILURE"),
    ("status FAILURE→SUCCESS", r"::FAILURE\b", "::SUCCESS"),
    ("status OK→EXECUTION_ERROR", r"CmdResponse::OK\b", "CmdResponse::EXECUTION_ERROR"),
    ("status OP_OK→OTHER_ERROR", r"::OP_OK\b", "::OTHER_ERROR"),
    ("const +1→+0", r"\+\s*1\b(?!\.)", "+ 0"),
    ("const -1→-0", r"-\s*1\b(?!\.)", "- 0"),
]
# statements whose deletion removes an observable effect (port output, event, telemetry, command response)
_EFFECT_STMT = re.compile(r"^\s*(?:this->)?(?:\w+_out|tlmWrite_\w+|log_\w+)\s*\(.*\)\s*;\s*$")
_SKIP_LINE = re.compile(r"^\s*(//|/\*|\*|#)|FW_ASSERT|static_assert")


@dataclass
class Mutant:
    file: str
    line: int
    operator: str
    original: str
    mutated: str


@dataclass
class MutationReport:
    candidates: int
    sampled: int
    valid: int
    killed: int
    mutants: list[dict[str, Any]]

    @property
    def score(self) -> float | None:
        return round(self.killed / self.valid, 4) if self.valid else None

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "score": self.score}


def candidates(path: Path, lines: set[int]) -> list[Mutant]:
    src = path.read_text(encoding="utf-8").splitlines()
    out = []
    for n in sorted(lines):
        if n < 1 or n > len(src):
            continue
        text = src[n - 1]
        if _SKIP_LINE.search(text):
            continue
        code, _, _ = text.partition("//")
        for name, pattern, repl in OPERATORS:
            for m in re.finditer(pattern, code):
                mutated = text[: m.start()] + repl + text[m.end() :]
                out.append(Mutant(str(path), n, name, text, mutated))
        if _EFFECT_STMT.match(code):
            indent = text[: len(text) - len(text.lstrip())]
            out.append(
                Mutant(str(path), n, "delete effect statement", text, f"{indent};  // mutant: deleted")
            )
    return out


def sample(muts: list[Mutant], n: int, seed: str) -> list[Mutant]:
    """Up to n mutants, spread over operators first, deterministic for a given seed."""
    rng = random.Random(seed)
    by_op: dict[str, list[Mutant]] = {}
    for m in muts:
        by_op.setdefault(m.operator, []).append(m)
    for v in by_op.values():
        rng.shuffle(v)
    ops = sorted(by_op)
    rng.shuffle(ops)
    picked: list[Mutant] = []
    while len(picked) < n and any(by_op.values()):
        for op in ops:
            if by_op[op] and len(picked) < n:
                picked.append(by_op[op].pop())
    return picked


def analyse(ws: FprimeWorkspace, c: Component, gtest_filter: str, n: int, seed: str) -> MutationReport:
    """Run the new test against up to ``n`` mutants of the lines it covers. Leaves a clean, rebuilt tree."""
    ws.reset_coverage(c)
    ws.run_ut(c, gtest_filter)
    covered = ws.covered_lines(c)
    pool = [m for path, lines in covered.items() for m in candidates(path, lines)]
    picked = sample(pool, n, seed)
    results, valid, killed = [], 0, 0
    originals = {Path(m.file): Path(m.file).read_text(encoding="utf-8") for m in picked}
    try:
        for m in picked:
            path = Path(m.file)
            lines = originals[path].splitlines(keepends=True)
            eol = "\n" if lines[m.line - 1].endswith("\n") else ""
            lines[m.line - 1] = m.mutated + eol
            path.write_text("".join(lines), encoding="utf-8")
            build = ws.build_ut(c)
            outcome = "invalid"
            if build.ok:
                valid += 1
                run = ws.run_ut(c, gtest_filter, timeout_s=60)
                outcome = "killed" if not run.passed else "survived"
                killed += outcome == "killed"
            path.write_text(originals[path], encoding="utf-8")
            results.append({**asdict(m), "file": str(path.relative_to(ws.repo)), "outcome": outcome})
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8")
        if picked:
            ws.build_ut(c)
    return MutationReport(len(pool), len(picked), valid, killed, results)
