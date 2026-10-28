"""Prompt context of the test-writing agent: requirement, model, harness API, tests, implementation.

Context is assembled deterministically from the knowledge graph (over MCP) and the component's files, in
priority order under a character budget, so that runs are reproducible and comparable across models.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from onprem_genai.agent.fprime import (
    Component,
    FprimeWorkspace,
    component_kind,
    component_member,
    tester_methods,
)
from onprem_genai.agent.knowledge import KnowledgeClient

SYSTEM_PROMPT = """\
You are a senior flight-software test engineer working on NASA F Prime (F´) components (C++14).
Your job: write ONE focused unit test that verifies ONE requirement, using the component's existing
gtest harness.

Rules (from the F´ unit-testing guidelines):
- Test through the component's interface only: invoke input ports (invoke_to_*), send commands (sendCmd_*),
  then assert on output ports (ASSERT_from_*), events (ASSERT_EVENTS_*), telemetry (ASSERT_TLM_*) and command
  responses (ASSERT_CMD_RESPONSE*). Use only macros and methods listed in the harness API.
- Call this->clearHistory() before the action you check. Dispatch messages only as the "dispatch" line of
  the requirement section says: passive components have no message queue and nothing to dispatch.
- Derive expected values from the requirement and the FPP model, never from guesses. Check values,
  not only sizes.
- Reuse the existing Tester helpers, members and constructor modes shown below; do not modify existing code.
- No dynamic memory, threads, sleeps, file deletion or process control.
- The tests build with -Werror: use static_cast / reinterpret_cast (no C-style casts) and no deprecated APIs.

Answer format: optionally one short paragraph of reasoning, then exactly two fenced blocks:
```cpp tester
<one or more new member function definitions of the Tester class, written as `void <Tester>::name() {...}`;
 #include lines allowed at the top of this block>
```
```cpp main
<one or more new TEST(Suite, Name) cases that construct the Tester like the existing cases and call
 your method>
```
Start the test method with REQUIREMENT("<requirement id>");. Use new, descriptive method and test names.
If the requirement cannot be verified by a unit test of this component (e.g. it is verified by inspection of
the FPP model or needs real hardware or OS process control), answer only: NOT_TESTABLE: <one-sentence reason>.
"""

REPAIR_BUILD = """\
The test did not compile. Diagnostics (paths relative to the repository):
{errors}
{hints}
Fix the problem and answer again with the ```cpp tester``` and ```cpp main``` blocks (a block you leave
out is taken unchanged from your previous answer)."""

REPAIR_POLICY = """\
The answer was rejected before building: {error}
Answer again with the ```cpp tester``` and ```cpp main``` blocks (a block you leave out is taken unchanged
from your previous answer)."""

REPAIR_TEST = """\
The test compiled but failed:
{failures}
{hints}Re-read the requirement and the implementation. If the expectation in the test is wrong, fix the test
and answer again (a block you leave out is taken unchanged from your previous answer). If you are confident
the test is right and the implementation violates the requirement, answer SUSPECTED_DEFECT:
<one-paragraph explanation> followed by the unchanged blocks."""

REPAIR_REGRESSION = """\
Your test passes, but the existing unit tests now fail:
{failures}
Your change must not affect other tests (shared state, name clashes, history size). Fix it and answer
again (a block you leave out is taken unchanged from your previous answer)."""


@dataclass
class ContextSection:
    title: str
    body: str
    lang: str = ""
    priority: int = 0  # lower = more important


@dataclass
class AgentContext:
    req_id: str
    requirement: dict[str, Any]
    sections: list[ContextSection] = field(default_factory=list)
    api_names: list[str] = field(default_factory=list)
    known_names: list[str] = field(default_factory=list)  # identifiers of the tester and component headers
    dropped: list[str] = field(default_factory=list)

    def render(self, budget_chars: int) -> str:
        used, parts = 0, []
        for s in sorted(self.sections, key=lambda s: s.priority):
            block = (
                f"### {s.title}\n```{s.lang}\n{s.body.strip()}\n```\n"
                if s.lang
                else f"### {s.title}\n{s.body}\n"
            )
            if used + len(block) > budget_chars:
                room = budget_chars - used - 200
                if room > 1500 and s.lang:  # keep the head of a large file rather than nothing
                    block = f"### {s.title} (truncated)\n```{s.lang}\n{s.body[:room].rstrip()}\n// ...\n```\n"
                else:
                    self.dropped.append(s.title)
                    continue
            parts.append(block)
            used += len(block)
        return "\n".join(parts)


# ------------------------------------------------------------------------------------------- harness API
_MACRO = re.compile(r"#define\s+((?:ASSERT|EXPECT)_\w+)\s*\(([^)]*)\)")
_METHOD = re.compile(
    r"([A-Za-z_][\w:<>]*\s*[&*]?)\s+((?:invoke_to|sendCmd|paramSet|paramSend|paramSave|dispatch)\w*)\s*\(([^)]*)\)\s*;"
)


def harness_api(ws: FprimeWorkspace, c: Component) -> tuple[str, list[str]]:
    """Assertion macros and port / command helpers of the autocoded harness (needs a generated UT build)."""
    out, names = [], []
    base = ws.autocode_dir(c)
    gtest = base / f"{c.name}GTestBase.hpp"
    tbase = base / f"{c.name}TesterBase.hpp"
    if gtest.exists():
        for m in _MACRO.finditer(gtest.read_text(encoding="utf-8", errors="replace")):
            names.append(m.group(1))
            out.append(f"{m.group(1)}({', '.join(a.strip() for a in m.group(2).split(','))})")
    if tbase.exists():
        text = re.sub(r"//[^\n]*", "", tbase.read_text(encoding="utf-8", errors="replace"))
        for m in _METHOD.finditer(text):
            if m.group(2).endswith(("_static", "Base")):
                continue
            names.append(m.group(2))
            out.append(f"{' '.join(m.group(1).split())} {m.group(2)}({' '.join(m.group(3).split())})")
        names.append("clearHistory")
        out.append("void clearHistory()")
    return "\n".join(dict.fromkeys(out)), sorted(set(names))


def dispatch_rule(c: Component) -> str:
    """How the test must process the component's messages, stated per component (models over-apply
    doDispatch() to passive components when told only the general rule)."""
    kind = component_kind(c)
    member = component_member(c) or "component"
    if kind == "passive":
        return (
            f"{c.name} is a passive component: invoke_to_* and sendCmd_* run its handlers synchronously "
            "before they return. There is no message queue: never call doDispatch() or any dispatch helper."
        )
    if kind in ("active", "queued"):
        return (
            f"{c.name} is an {kind} component: async input ports and commands are queued. After each "
            f"invoke_to_* on an async port or sendCmd_*, call this->{member}.doDispatch() once per message "
            "before asserting (sync and guarded ports run immediately)."
        )
    return "unknown component kind: follow the existing tests"


# ------------------------------------------------------------------------------------------- assembly
def _read(p: Path, limit: int | None = None) -> str:
    text = p.read_text(encoding="utf-8", errors="replace")
    return text if limit is None else text[:limit]


async def build_context(ws: FprimeWorkspace, kb: KnowledgeClient, c: Component, req_id: str) -> AgentContext:
    req = await kb.requirement(req_id)
    if "error" in req:
        raise ValueError(req["error"])
    trace = await kb.trace(req_id, k=6)
    ctx = AgentContext(req_id, req)
    ctx.sections.append(
        ContextSection(
            "Requirement",
            f"- id: {req_id}\n- text: {req.get('text', '').strip()}\n"
            f"- verification: {req.get('verification', '')}\n"
            f"- component: {c.module} (Tester class `{c.tester_class}`, component under test: "
            f"`this->{component_member(c) or 'component'}`)\n"
            f"- dispatch: {dispatch_rule(c)}",
            priority=0,
        )
    )
    docs = await kb.search(req.get("text", ""), k=2, kinds=["DocChunk"], module=c.module)
    if docs:
        ctx.sections.append(
            ContextSection(
                "Design document excerpts",
                "\n\n".join(f"[{d['title']}]\n{d.get('snippet', '')}" for d in docs),
                priority=8,
            )
        )
    for fpp in c.fpp_files:
        ctx.sections.append(ContextSection(f"FPP model {fpp.name}", _read(fpp, 9000), "fpp", priority=1))
    api, ctx.api_names = harness_api(ws, c)
    if api:
        ctx.sections.append(ContextSection("Test harness API (autocoded)", api, "cpp", priority=2))
    ctx.sections.append(ContextSection(f"{c.tester_hpp.name}", _read(c.tester_hpp), "cpp", priority=3))
    idents: set[str] = set()
    for h in [c.tester_hpp, *c.impl_headers]:
        idents |= set(re.findall(r"\b[A-Za-z_]\w{3,}\b", _read(h)))
    ctx.known_names = sorted(idents)
    ctx.sections.append(ContextSection(f"{c.test_main.name}", _read(c.test_main), "cpp", priority=4))

    methods = tester_methods(c)
    examples: list[str] = []
    for t in trace.get("suggested_tests", []):
        name = t["title"].rsplit("::", 1)[-1]
        if name in methods and name not in examples and not t["title"].startswith("TEST("):
            examples.append(name)
    for helper in ("connectPorts", "initComponents"):  # how the harness is wired
        if helper in methods and helper not in examples:
            examples.append(helper)
    if examples:
        ctx.sections.append(
            ContextSection(
                f"Existing tests and helpers in {c.tester_cpp.name} (most related first)",
                "\n\n".join(methods[n][2] for n in examples[:4]),
                "cpp",
                priority=5,
            )
        )
    impl_size = sum(p.stat().st_size for p in c.impl_sources)
    for h in c.impl_headers:
        ctx.sections.append(
            ContextSection(f"Implementation header {h.name}", _read(h, 8000), "cpp", priority=6)
        )
    if impl_size <= 12000:
        for s in c.impl_sources:
            ctx.sections.append(ContextSection(f"Implementation {s.name}", _read(s), "cpp", priority=7))
    else:
        related = [h for h in trace.get("related_code", [])][:4]
        snippets = []
        for h in related:
            short = h["title"].rsplit("::", 1)[-1].split("(")[0]
            for sym in await kb.symbol(short, module=c.module):
                if sym["id"] == h["id"]:
                    snippets.append(sym.get("text", ""))
        if snippets:
            ctx.sections.append(
                ContextSection(
                    "Implementation functions related to the requirement",
                    "\n\n".join(snippets),
                    "cpp",
                    priority=7,
                )
            )
    return ctx


def task_message(ctx: AgentContext, budget_chars: int) -> str:
    return (
        f"{ctx.render(budget_chars)}\n"
        f"Write one unit test that verifies requirement {ctx.req_id}. "
        f'Start the test method with REQUIREMENT("{ctx.req_id}");.'
    )


# ------------------------------------------------------------------------------------------- repair hints
_UNKNOWN = [
    re.compile(r"[‘'`](\w+)[’'`] was not declared in this scope"),
    re.compile(r"has no member named [‘'`](\w+)[’'`]"),
    re.compile(r"[‘'`](\w+)[’'`] is not a member of"),
    re.compile(r"[‘'`](\w+)[’'`] was not declared"),
    re.compile(r"no matching function for call to [‘'`][\w:]*?(\w+)\("),
]


async def repair_hints(errors: str, ctx: AgentContext, kb: KnowledgeClient, c: Component) -> str:
    """Error-driven retrieval: suggest close harness names and show definitions of unknown symbols."""
    unknown = list(dict.fromkeys(m.group(1) for rx in _UNKNOWN for m in rx.finditer(errors)))[:6]
    hints = []
    if any("dispatch" in n.lower() for n in unknown):
        hints.append(f"- {dispatch_rule(c)}")
        unknown = [n for n in unknown if "dispatch" not in n.lower()]
    for name in unknown:
        close = difflib.get_close_matches(name, ctx.api_names, n=3, cutoff=0.6) or difflib.get_close_matches(
            name, ctx.known_names, n=3, cutoff=0.75
        )
        if close and name not in close:
            hints.append(f"- `{name}` does not exist; similar names that do: {', '.join(close)}")
            continue
        syms = await kb.symbol(name, module=c.module) or await kb.symbol(name)
        if syms:
            s = syms[0]
            hints.append(
                f"- `{name}` is defined at {s.get('location')}:\n```cpp\n{s.get('text', '')[:1200]}\n```"
            )
    return ("Hints:\n" + "\n".join(hints) + "\n") if hints else ""


_FW_ASSERT = re.compile(r'Assert: "([^"]+?):(\d+)"')


def assert_hints(failures: str, repo: Path, context_lines: int = 4) -> str:
    """Source of each F´ assertion (FW_ASSERT) a failing test triggered, i.e. the precondition it broke."""
    hints = []
    for path, line in list(dict.fromkeys(_FW_ASSERT.findall(failures)))[:3]:
        f = Path(path) if Path(path).is_absolute() else repo / path
        if not f.is_file():
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        n = int(line)
        if not 1 <= n <= len(lines):
            continue
        first = max(1, n - context_lines)
        excerpt = "\n".join(f"{'>' if i == n else ' '} {i:4d} | {lines[i - 1]}" for i in range(first, n + 1))
        shown = f.relative_to(repo) if f.is_relative_to(repo) else f
        hints.append(
            f"- the component asserted (FW_ASSERT) at {shown}:{n}; the test broke this precondition:\n"
            f"```cpp\n{excerpt}\n```"
        )
    return ("Hints:\n" + "\n".join(hints) + "\n") if hints else ""
