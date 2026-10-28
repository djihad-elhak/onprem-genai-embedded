"""F´ workspace operations used by the agent: component layout, unit-test build and run, coverage, git.

Everything here is deterministic and bounded (timeouts, output caps). The LLM never runs commands: the agent
graph calls these functions with arguments derived from the requirement, never from model output.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from onprem_genai.knowledge.fprime.cpp import parse_cpp

UT_BUILD_DIR = "build-fprime-automatic-native-ut"
BUILD_TIMEOUT_S = 900
RUN_TIMEOUT_S = 300


class UnsupportedComponentError(RuntimeError):
    """The component's unit-test layout is not the standard Tester / TestMain one."""


@dataclass
class Component:
    module: str  # e.g. Svc/ComStub
    root: Path
    tester_class: str  # e.g. ComStubTester
    tester_hpp: Path
    tester_cpp: Path
    test_main: Path
    fpp_files: list[Path]
    impl_sources: list[Path]
    impl_headers: list[Path]

    @property
    def name(self) -> str:
        return self.module.rsplit("/", 1)[-1]

    @property
    def target(self) -> str:
        return self.module.replace("/", "_")

    @property
    def test_files(self) -> list[Path]:
        return [self.tester_hpp, self.tester_cpp, self.test_main]


def find_component(repo: Path, module: str) -> Component:
    module = module.removeprefix("module:")
    root = repo / module
    ut = root / "test" / "ut"
    if not ut.is_dir():
        raise UnsupportedComponentError(f"{module}: no test/ut directory")
    hpps = [
        p for p in sorted(ut.glob("*Tester.hpp")) if not p.name.endswith(("TesterBase.hpp", "GTestBase.hpp"))
    ]
    if len(hpps) != 1:
        raise UnsupportedComponentError(f"{module}: expected one *Tester.hpp, found {[p.name for p in hpps]}")
    hpp = hpps[0]
    cpp = hpp.with_suffix(".cpp")
    m = re.search(
        r"class\s+(\w+)\s*(?:final\s*)?:\s*public\s+[\w:]*GTestBase\b", hpp.read_text(encoding="utf-8")
    )
    if not cpp.is_file() or not m:
        raise UnsupportedComponentError(f"{module}: tester class or implementation not found")
    mains = [p for p in sorted(ut.glob("*.cpp")) if p != cpp and "TEST(" in p.read_text(encoding="utf-8")]
    if len(mains) != 1:
        raise UnsupportedComponentError(f"{module}: expected one file with TEST() cases, found {len(mains)}")
    return Component(
        module=module,
        root=root,
        tester_class=m.group(1),
        tester_hpp=hpp,
        tester_cpp=cpp,
        test_main=mains[0],
        fpp_files=sorted(root.glob("*.fpp")),
        impl_sources=sorted(p for p in root.glob("*.cpp") if not p.name.endswith("Ac.cpp")),
        impl_headers=sorted(p for p in root.glob("*.hpp") if not p.name.endswith("Ac.hpp")),
    )


# ------------------------------------------------------------------------------------------- build & run
@dataclass
class BuildResult:
    ok: bool
    seconds: float
    errors: str  # compiler / linker diagnostics, condensed for the model
    log_tail: str


@dataclass
class TestRun:
    ran: bool
    passed: bool
    seconds: float
    tests: int = 0
    failures: list[str] = field(default_factory=list)  # "Suite.Name: message"
    output_tail: str = ""


_DIAG = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:(?P<col>\d+):)? (?:fatal )?error: (?P<msg>.*)$")


def condense_diagnostics(log: str, repo: Path, max_chars: int = 3500) -> str:
    """First compiler errors (with their source excerpt) and linker errors, with repo-relative paths."""
    lines = log.splitlines()
    out: list[str] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        m = _DIAG.match(line)
        if m:
            key = f"{m['file']}:{m['line']}:{m['msg']}"
            if key in seen:
                continue
            seen.add(key)
            out.append(line.replace(str(repo) + "/", ""))
            out.extend(ln for ln in lines[i + 1 : i + 3] if ln.startswith(" ") and "|" in ln)
        elif "undefined reference to" in line or "multiple definition of" in line:
            out.append(line.split(": ", 1)[-1] if ".o:" in line else line)
        if sum(len(x) + 1 for x in out) > max_chars:
            out.append("... (more errors truncated)")
            break
    if not out and log.strip():
        out = [ln for ln in lines if "rror" in ln][:20] or lines[-20:]
    return "\n".join(out)[: max_chars + 200]


class FprimeWorkspace:
    """A checked-out F´ repository with a generated unit-test build cache (``fprime-util generate --ut``)."""

    def __init__(self, repo: Path, fprime_util: str | None = None, jobs: int | None = None) -> None:
        self.repo = repo.resolve()
        self.build_dir = self.repo / UT_BUILD_DIR
        bundled = repo.absolute().parent / "fprime-venv" / "bin" / "fprime-util"  # scripts/setup_fprime_ut.sh
        found = shutil.which("fprime-util") or (str(bundled) if bundled.exists() else "fprime-util")
        self.fprime_util = fprime_util or found
        tool_dir = str(Path(self.fprime_util).parent) if os.sep in self.fprime_util else ""
        # fprime-util drives cmake / ninja / fpp from the same environment
        self.env = {**os.environ, "PATH": f"{tool_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        self.jobs = jobs or max(1, (os.cpu_count() or 2))

    # -- layout
    def component(self, module: str) -> Component:
        return find_component(self.repo, module)

    def ut_binary(self, c: Component) -> Path | None:
        hits = sorted((self.build_dir / "bin").glob(f"*/{c.target}_ut_exe"))
        return hits[0] if hits else None

    def autocode_dir(self, c: Component) -> Path:
        return self.build_dir / "F-Prime" / c.module

    # -- build
    def build_ut(self, c: Component, timeout_s: int = BUILD_TIMEOUT_S) -> BuildResult:
        t0 = time.perf_counter()
        cmd = [self.fprime_util, "build", "--ut", f"-j{self.jobs}"]
        try:
            p = subprocess.run(
                cmd, cwd=c.root, capture_output=True, text=True, timeout=timeout_s, check=False, env=self.env
            )
            log = p.stdout + p.stderr
            ok = p.returncode == 0
        except subprocess.TimeoutExpired as exc:
            log, ok = f"build timed out after {timeout_s}s\n{exc.stdout or ''}", False
        dt = time.perf_counter() - t0
        return BuildResult(ok, round(dt, 2), "" if ok else condense_diagnostics(log, self.repo), log[-4000:])

    def run_ut(
        self, c: Component, gtest_filter: str | None = None, repeat: int = 1, timeout_s: int = RUN_TIMEOUT_S
    ) -> TestRun:
        exe = self.ut_binary(c)
        if exe is None:
            return TestRun(False, False, 0.0, output_tail="unit-test executable not found")
        with tempfile.TemporaryDirectory(prefix="oge-gtest-") as tmp:
            report = Path(tmp) / "report.json"
            cmd = [str(exe), f"--gtest_output=json:{report}", f"--gtest_repeat={repeat}"]
            if gtest_filter:
                cmd.append(f"--gtest_filter={gtest_filter}")
            t0 = time.perf_counter()
            try:
                p = subprocess.run(
                    cmd, cwd=c.root, capture_output=True, text=True, timeout=timeout_s, check=False
                )
                out, code = p.stdout + p.stderr, p.returncode
            except subprocess.TimeoutExpired:
                return TestRun(True, False, timeout_s, failures=[f"timeout after {timeout_s}s"])
            dt = round(time.perf_counter() - t0, 2)
            tests, failures = _parse_gtest_report(report)
        if code != 0 and not failures:  # crash or FW_ASSERT before the report was written
            failures = [f"executable exited with code {code}: {_tail(out, 1500)}"]
        prefix = str(self.repo) + "/"
        failures = [f.replace(prefix, "") for f in failures]
        out = out.replace(prefix, "")
        return TestRun(True, code == 0 and not failures and tests > 0, dt, tests, failures, _tail(out, 3000))

    def list_tests(self, c: Component) -> list[str]:
        exe = self.ut_binary(c)
        if exe is None:
            return []
        p = subprocess.run(
            [str(exe), "--gtest_list_tests"],
            cwd=c.root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        names, suite = [], ""
        for line in p.stdout.splitlines():
            if line and not line.startswith(" ") and line.endswith("."):
                suite = line[:-1]
            elif line.startswith("  ") and suite:
                names.append(f"{suite}.{line.strip().split()[0]}")
        return names

    # -- coverage
    def reset_coverage(self, c: Component) -> None:
        for p in self.autocode_dir(c).rglob("*.gcda"):
            p.unlink()

    def coverage(self, c: Component) -> dict[str, float]:
        """Line / branch coverage of the component implementation (not autocode) from the last runs."""
        obj_dir = self.autocode_dir(c) / "CMakeFiles" / f"{c.target}.dir"
        executed = total = taken = branches = 0
        for src in c.impl_sources:
            gcda = obj_dir / f"{src.name}.gcda"
            if not gcda.exists():
                continue
            p = subprocess.run(
                ["gcov", "-b", "-n", "-o", str(obj_dir), str(gcda)],
                capture_output=True,
                text=True,
                cwd=obj_dir,
                timeout=60,
                check=False,
            )
            block = p.stdout.split(f"File '{src}'", 1)
            if len(block) < 2:
                continue
            body = block[1].split("File '", 1)[0]
            if m := re.search(r"Lines executed:([\d.]+)% of (\d+)", body):
                n = int(m.group(2))
                executed += round(float(m.group(1)) * n / 100)
                total += n
            if m := re.search(r"Taken at least once:([\d.]+)% of (\d+)", body):
                n = int(m.group(2))
                taken += round(float(m.group(1)) * n / 100)
                branches += n
        return {
            "line_coverage": round(executed / total, 4) if total else 0.0,
            "branch_coverage": round(taken / branches, 4) if branches else 0.0,
            "lines": total,
        }

    def covered_lines(self, c: Component) -> dict[Path, set[int]]:
        """Executed line numbers per implementation file (gcov intermediate text format)."""
        obj_dir = self.autocode_dir(c) / "CMakeFiles" / f"{c.target}.dir"
        out: dict[Path, set[int]] = {}
        for src in c.impl_sources:
            gcda = obj_dir / f"{src.name}.gcda"
            if not gcda.exists():
                continue
            with tempfile.TemporaryDirectory(prefix="oge-gcov-") as tmp:
                subprocess.run(
                    ["gcov", "-b", "-o", str(obj_dir), str(gcda)],
                    capture_output=True,
                    text=True,
                    cwd=tmp,
                    timeout=60,
                    check=False,
                )
                report = Path(tmp) / f"{src.name}.gcov"
                if not report.exists():
                    continue
                hit = set()
                for line in report.read_text(encoding="utf-8", errors="replace").splitlines():
                    count, _, rest = line.partition(":")
                    lineno, _, _ = rest.partition(":")
                    count = count.strip().rstrip("*")
                    if count.isdigit() and int(count) > 0 and lineno.strip().isdigit():
                        hit.add(int(lineno))
                out[src] = hit
        return out

    # -- git
    def git(self, *args: str, check: bool = True) -> str:
        p = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=False)
        if check and p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
        return p.stdout.strip()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def start_branch(self, name: str) -> None:
        """Create (or reset) a working branch at the current HEAD and switch to it."""
        self.git("checkout", "-q", "-B", name)

    def restore(self, paths: list[Path]) -> None:
        self.git("checkout", "-q", "HEAD", "--", *[str(p.relative_to(self.repo)) for p in paths])

    def diff(self, paths: list[Path]) -> str:
        return self.git("diff", "--", *[str(p.relative_to(self.repo)) for p in paths], check=False)

    def changed_files(self) -> list[str]:
        out = self.git("status", "--porcelain", "--untracked-files=all", check=False)
        return [line[3:] for line in out.splitlines() if line.strip()]

    def commit(self, paths: list[Path], message: str, author: str) -> str:
        self.git("add", "--", *[str(p.relative_to(self.repo)) for p in paths])
        self.git(
            "-c",
            "user.name=oge-agent",
            "-c",
            "user.email=oge-agent@localhost",
            "commit",
            "-q",
            f"--author={author}",
            "-m",
            message,
        )
        return self.head()


def _parse_gtest_report(report: Path) -> tuple[int, list[str]]:
    if not report.exists():
        return 0, []
    data = json.loads(report.read_text(encoding="utf-8"))
    tests, failures = 0, []
    for suite in data.get("testsuites", []):
        for case in suite.get("testsuite", []):
            tests += 1
            for f in case.get("failures", []):
                msg = " ".join(str(f.get("failure", "")).split())[:600]
                failures.append(f"{suite.get('name')}.{case.get('name')}: {msg}")
    return tests, failures


def _tail(text: str, n: int) -> str:
    return text if len(text) <= n else "..." + text[-n:]


def tester_methods(c: Component) -> dict[str, tuple[int, int, str]]:
    """Tester member functions defined in the tester .cpp: name -> (start_line, end_line, text)."""
    info = parse_cpp(c.tester_cpp.read_bytes())
    return {
        f.name: (f.start_line, f.end_line, f.text) for f in info.functions if f.class_name == c.tester_class
    }


def test_cases(c: Component) -> dict[str, str]:
    """``Suite.Name`` -> TEST() block text in the test main file."""
    info = parse_cpp(c.test_main.read_bytes())
    return {f.name: f.text for f in info.functions if f.is_gtest_case}


def component_kind(c: Component) -> str | None:
    """``active``, ``passive`` or ``queued``, from the component's FPP model."""
    for fpp in c.fpp_files:
        text = fpp.read_text(encoding="utf-8", errors="replace")
        m = re.search(rf"\b(active|passive|queued)\s+component\s+{re.escape(c.name)}\b", text)
        if m:
            return m.group(1)
    return None


def component_member(c: Component) -> str | None:
    """Name of the Tester member that holds the component under test (``component``, ``m_impl``, ...)."""
    impl = None
    for h in c.impl_headers:
        m = re.search(
            rf"class\s+(\w+)\s*(?:final\s*)?:\s*public\s+(?:\w+::)*{re.escape(c.name)}ComponentBase\b",
            h.read_text(encoding="utf-8", errors="replace"),
        )
        if m:
            impl = m.group(1)
            break
    if impl is None:
        return None
    m = re.search(rf"(?:\w+::)*\b{impl}\s*[&*]?\s+(\w+)\s*;", c.tester_hpp.read_text(encoding="utf-8"))
    return m.group(1) if m else None
