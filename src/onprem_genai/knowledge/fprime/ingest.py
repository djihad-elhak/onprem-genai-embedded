"""Build the knowledge graph of an F´ checkout: modules, code, tests, requirements and design docs."""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from onprem_genai.knowledge.fprime.cpp import FunctionInfo, parse_cpp
from onprem_genai.knowledge.fprime.requirements import RequirementRow, parse_sdd
from onprem_genai.knowledge.model import EdgeType, Graph, Node, NodeType

DEFAULT_TOP_DIRS = ("Fw", "Os", "Svc", "Drv", "Utils", "CFDP")
CODE_SUFFIXES = (".cpp", ".hpp", ".c", ".h")
MAX_AMBIGUOUS_TARGETS = 3
DOC_CHUNK_CHARS = 1500
_HEADING = re.compile(r"^#{1,4}\s+(.*)$")


@dataclass
class IngestReport:
    files: int
    loc: int
    functions: int
    test_cases: int
    requirements: int
    sdd_files: int
    sdd_files_with_tables: int
    tags: int
    tags_resolved: int
    tags_to_undefined_requirement: list[str]
    tags_cross_module: list[str]
    calls_resolved: int
    calls_total: int


def is_test_path(rel: Path) -> bool:
    return "test" in rel.parts[:-1]


def module_of(rel: Path, root: Path) -> Path:
    """Module directory: the nearest ancestor (outside any test/ tree) that has a CMakeLists.txt."""
    parts = list(rel.parts[:-1])
    if "test" in parts:
        parts = parts[: parts.index("test")]
    d = Path(*parts) if parts else Path()
    while d != Path() and not (root / d / "CMakeLists.txt").exists():
        d = d.parent
    return d if d != Path() else Path(rel.parts[0])


def _fprime_short_name_aliases(call: str) -> list[str]:
    """F´ autocoder conventions: tests drive a component through generated helpers.

    ``sendCmd_FOO`` -> command handler ``FOO_cmdHandler``;
    ``invoke_to_bar`` -> input port handler ``bar_handler``.
    """
    if call.startswith("sendCmd_"):
        return [call, f"{call.removeprefix('sendCmd_')}_cmdHandler"]
    if call.startswith("invoke_to_"):
        return [call, f"{call.removeprefix('invoke_to_')}_handler"]
    return [call]


def _doc_chunks(markdown: str) -> list[tuple[str, str]]:
    """Split a design document by headings, skipping requirement tables (they become Requirement nodes)."""
    chunks: list[tuple[str, str]] = []
    heading, buf = "Overview", []
    for line in [*markdown.splitlines(), "# <end>"]:
        m = _HEADING.match(line)
        if m:
            body = "\n".join(buf).strip()
            if body and "requirement" not in heading.lower():
                for k in range(0, len(body), DOC_CHUNK_CHARS):
                    chunks.append((heading, body[k : k + DOC_CHUNK_CHARS]))
            heading, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    return chunks


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


class _GraphBuilder:
    """Incremental construction of the F´ graph; one method per ingestion stage."""

    def __init__(self, root: Path, top_dirs: tuple[str, ...]) -> None:
        self.root, self.top_dirs = root, top_dirs
        self.g = Graph()
        self.g.meta = {"source": "nasa/fprime", "commit": _git_commit(root), "top_dirs": list(top_dirs)}
        self.func_index: dict[str, list[str]] = defaultdict(list)  # short name -> non-test function ids
        self.module_of_node: dict[str, str] = {}
        self.pending_calls: list[tuple[str, list[str]]] = []
        self.pending_tags: list[tuple[str, str, int]] = []
        self.loc = 0

    def _files(self, suffixes: tuple[str, ...]) -> list[Path]:
        return sorted(
            p
            for d in self.top_dirs
            if (self.root / d).is_dir()
            for p in (self.root / d).rglob("*")
            if p.suffix in suffixes
        )

    def ensure_module(self, mod: Path) -> str:
        mid = f"module:{mod.as_posix()}"
        if mid not in self.g.nodes:
            self.g.add_node(Node(mid, NodeType.MODULE, {"path": mod.as_posix(), "name": mod.as_posix()}))
        return mid

    # ---------------------------------------------------------------- stage 1: source code
    def add_code_file(self, path: Path) -> None:
        g, rel = self.g, path.relative_to(self.root)
        info = parse_cpp(path.read_bytes())
        self.loc += info.loc
        test = is_test_path(rel)
        mid = self.ensure_module(module_of(rel, self.root))
        fid = f"file:{rel.as_posix()}"
        g.add_node(
            Node(
                fid,
                NodeType.FILE,
                {"path": rel.as_posix(), "loc": info.loc, "is_test": test, "includes": info.includes},
            )
        )
        g.add_edge(mid, fid, EdgeType.CONTAINS)
        for c in info.classes:
            cid = f"class:{rel.as_posix()}#{c.qualified}"
            props = {
                "name": c.name,
                "qualified": c.qualified,
                "file": rel.as_posix(),
                "line": c.line,
                "bases": c.bases,
            }
            g.add_node(Node(cid, NodeType.CLASS, props))
            g.add_edge(fid, cid, EdgeType.DEFINES)
        for fn in info.functions:
            self._add_function(fn, rel, fid, mid, test)

    def _add_function(self, fn: FunctionInfo, rel: Path, fid: str, mid: str, test: bool) -> None:
        is_case = test and (fn.is_gtest_case or bool(fn.requirement_tags) or _looks_like_test(fn))
        ntype = NodeType.TEST_CASE if is_case else NodeType.FUNCTION
        nid = f"fn:{rel.as_posix()}#{fn.qualified}@{fn.start_line}"
        props = {
            "name": fn.name,
            "qualified": fn.qualified,
            "class": fn.class_name,
            "file": rel.as_posix(),
            "start_line": fn.start_line,
            "end_line": fn.end_line,
            "doc": fn.doc,
            "text": fn.text,
            "is_test_code": test,
        }
        self.g.add_node(Node(nid, ntype, props))
        self.g.add_edge(fid, nid, EdgeType.DEFINES)
        self.module_of_node[nid] = mid
        if ntype is NodeType.TEST_CASE:
            self.g.add_edge(nid, mid, EdgeType.TESTS)
        if not test:
            self.func_index[fn.name].append(nid)
        self.pending_calls.append((nid, fn.calls))
        self.pending_tags.extend((nid, rid, line) for rid, line in fn.requirement_tags)

    # ---------------------------------------------------------------- stage 2: requirements and design docs
    def add_markdown(self, path: Path) -> bool:
        """Add requirements (from tables) and doc chunks of one Markdown file; True if it had requirements."""
        g, rel = self.g, path.relative_to(self.root)
        parts = rel.parts[: rel.parts.index("docs")] if "docs" in rel.parts else rel.parts[:-1]
        mid = self.ensure_module(module_of(Path(*parts, "x.md"), self.root))
        rows = parse_sdd(path, self.root)
        for row in rows:
            self._add_requirement(row, mid)
        for k, (heading, body) in enumerate(_doc_chunks(path.read_text(encoding="utf-8", errors="replace"))):
            did = f"doc:{rel.as_posix()}#{k}"
            g.add_node(
                Node(did, NodeType.DOC_CHUNK, {"file": rel.as_posix(), "heading": heading, "text": body})
            )
            g.add_edge(did, mid, EdgeType.DESCRIBES)
        return bool(rows)

    def _add_requirement(self, row: RequirementRow, mid: str) -> None:
        rid = f"req:{row.req_id}"
        if rid in self.g.nodes:  # same ID defined twice: keep the first definition, record the duplicate
            self.g.nodes[rid].props.setdefault("duplicate_definitions", []).append(row.source_file)
            return
        props = {
            "req_id": row.req_id,
            "text": row.text,
            "verification": row.verification,
            "rationale": row.rationale,
            "file": row.source_file,
            "line": row.line,
        }
        self.g.add_node(Node(rid, NodeType.REQUIREMENT, props))
        self.g.add_edge(rid, mid, EdgeType.ALLOCATED_TO)

    # ---------------------------------------------------------------- stage 3: explicit traceability tags
    def link_tags(self) -> tuple[int, list[str], list[str]]:
        g, undefined, cross, resolved = self.g, [], [], 0
        for nid, req_id, line in self.pending_tags:
            rid = f"req:{req_id}"
            where = f"{g.nodes[nid].props['file']}:{line}"
            if rid not in g.nodes:
                undefined.append(f"{req_id} @ {where}")
                continue
            req_mod = g.successors(rid, EdgeType.ALLOCATED_TO)[0].id
            if req_mod != self.module_of_node[nid]:
                cross.append(f"{req_id} ({req_mod}) tagged in {where}")
            g.add_edge(nid, rid, EdgeType.VERIFIES, line=line)
            resolved += 1
        return resolved, sorted(set(undefined)), sorted(set(cross))

    # ---------------------------------------------------------------- stage 4: call resolution
    def resolve_calls(self) -> tuple[int, int]:
        """Name-based resolution: same-module targets first, else a unique-enough global match."""
        total = resolved = 0
        for nid, calls in self.pending_calls:
            my_mod = self.module_of_node[nid]
            for call in calls:
                total += 1
                targets: list[str] = []
                for alias in _fprime_short_name_aliases(call):
                    cands = self.func_index.get(alias, [])
                    local = [c for c in cands if self.module_of_node[c] == my_mod]
                    targets = local or (cands if 0 < len(cands) <= MAX_AMBIGUOUS_TARGETS else [])
                    if targets:
                        break
                for tgt in targets:
                    if tgt != nid:
                        self.g.add_edge(nid, tgt, EdgeType.CALLS)
                resolved += bool(targets)
        return resolved, total


def ingest_fprime(root: Path, top_dirs: tuple[str, ...] = DEFAULT_TOP_DIRS) -> tuple[Graph, IngestReport]:
    """Build the knowledge graph of an F´ checkout (deterministic for a given commit)."""
    b = _GraphBuilder(root.resolve(), top_dirs)
    code_files = b._files(CODE_SUFFIXES)
    for path in code_files:
        b.add_code_file(path)
    md_files = b._files((".md",))
    with_tables = sum(b.add_markdown(p) for p in md_files)
    tags_resolved, undefined, cross = b.link_tags()
    calls_resolved, calls_total = b.resolve_calls()
    g = b.g
    report = IngestReport(
        files=len(code_files),
        loc=b.loc,
        functions=len(g.of_type(NodeType.FUNCTION)),
        test_cases=len(g.of_type(NodeType.TEST_CASE)),
        requirements=len(g.of_type(NodeType.REQUIREMENT)),
        sdd_files=len(md_files),
        sdd_files_with_tables=with_tables,
        tags=len(b.pending_tags),
        tags_resolved=tags_resolved,
        tags_to_undefined_requirement=undefined,
        tags_cross_module=cross,
        calls_resolved=calls_resolved,
        calls_total=calls_total,
    )
    g.meta["ingest_report"] = {k: v for k, v in report.__dict__.items() if not isinstance(v, list)}
    return g, report


_TEST_NAME = re.compile(r"^(test|run|check|verify|nominal|off_?nominal)", re.IGNORECASE)


def _looks_like_test(fn: FunctionInfo) -> bool:
    """Tester methods that implement test scenarios (F´ convention: ``testX`` / ``runX`` / ``checkX``)."""
    return bool(_TEST_NAME.match(fn.name)) and not fn.name.startswith(("from_", "to_"))
