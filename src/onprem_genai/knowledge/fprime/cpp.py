"""C/C++ structure extraction with tree-sitter: functions, classes, calls, includes and doc comments."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

TEST_MACROS = frozenset({"TEST", "TEST_F", "TEST_P", "TYPED_TEST"})
REQUIREMENT_TAG = re.compile(r'REQUIREMENT\s*\(\s*"([^"]+)"\s*\)')
MAX_TEXT_CHARS = 6000


@dataclass
class FunctionInfo:
    name: str  # short name, e.g. runNominalDispatch, or Suite.Name for gtest macros
    qualified: str  # e.g. Svc::CommandDispatcherTester::runNominalDispatch
    class_name: str | None
    start_line: int
    end_line: int
    text: str
    doc: str
    calls: list[str] = field(default_factory=list)
    requirement_tags: list[tuple[str, int]] = field(default_factory=list)  # (id, line)
    is_gtest_case: bool = False


@dataclass
class ClassInfo:
    name: str
    qualified: str
    line: int
    bases: list[str]


@dataclass
class FileInfo:
    includes: list[str]
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    loc: int


@lru_cache(maxsize=1)
def _parser() -> Parser:
    return Parser(Language(tree_sitter_cpp.language()))


def cpp_parser() -> Parser:
    """Shared tree-sitter C++ parser."""
    return _parser()


def _text(src: bytes, node: Node) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _find_function_declarator(node: Node | None) -> Node | None:
    while node is not None:
        if node.type == "function_declarator":
            return node
        node = node.child_by_field_name("declarator")
    return None


def _leading_comments(node: Node, src: bytes) -> str:
    parts: list[str] = []
    prev = node.prev_sibling
    while prev is not None and prev.type == "comment":
        parts.append(_text(src, prev))
        prev = prev.prev_sibling
    return "\n".join(reversed(parts))


def _call_name(call: Node, src: bytes) -> str | None:
    fn = call.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type == "field_expression":
        fld = fn.child_by_field_name("field")
        return _text(src, fld) if fld is not None else None
    if fn.type == "template_function":
        name = fn.child_by_field_name("name")
        return _text(src, name).split("::")[-1] if name is not None else None
    if fn.type in ("identifier", "qualified_identifier", "field_identifier"):
        return _text(src, fn).split("::")[-1]
    return None


def _collect_calls(body: Node, src: bytes) -> list[str]:
    calls: list[str] = []
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type == "call_expression":
            name = _call_name(n, src)
            if name and name != "REQUIREMENT":
                calls.append(name)
        stack.extend(n.children)
    return calls


def parse_cpp(source: bytes) -> FileInfo:  # noqa: PLR0915  (single recursive tree visitor)
    tree = _parser().parse(source)
    functions: list[FunctionInfo] = []
    classes: list[ClassInfo] = []
    includes: list[str] = []

    def visit(node: Node, scope: list[str], class_name: str | None) -> None:
        for child in node.children:
            t = child.type
            if t == "preproc_include":
                path = child.child_by_field_name("path")
                if path is not None:
                    includes.append(_text(source, path).strip('"<>'))
            elif t == "namespace_definition":
                name = child.child_by_field_name("name")
                body = child.child_by_field_name("body")
                if body is not None:
                    visit(body, [*scope, _text(source, name)] if name is not None else scope, class_name)
            elif t in ("class_specifier", "struct_specifier"):
                name_node = child.child_by_field_name("name")
                body = child.child_by_field_name("body")
                if name_node is not None and body is not None:
                    cname = _text(source, name_node).split("::")[-1]
                    bases: list[str] = []
                    for clause in child.children:
                        if clause.type == "base_class_clause":
                            bases.extend(
                                _text(source, b).strip()
                                for b in clause.children
                                if b.type in ("type_identifier", "qualified_identifier", "template_type")
                            )
                    classes.append(
                        ClassInfo(cname, "::".join([*scope, cname]), child.start_point[0] + 1, bases)
                    )
                    visit(body, [*scope, cname], cname)
            elif t == "function_definition":
                fd = _find_function_declarator(child.child_by_field_name("declarator"))
                body = child.child_by_field_name("body")
                if fd is None or body is None:
                    continue
                decl = fd.child_by_field_name("declarator")
                if decl is None:
                    continue
                raw = re.sub(r"\s*::\s*", "::", _text(source, decl))
                is_gtest = raw in TEST_MACROS
                cls = class_name
                if is_gtest:
                    params = fd.child_by_field_name("parameters")
                    args = [a.strip() for a in _text(source, params).strip("()").split(",")] if params else []
                    name = ".".join(a for a in args if a) or raw
                    qualified = f"{raw}({', '.join(args)})"
                else:
                    segments = raw.split("::")
                    name = segments[-1]
                    if len(segments) > 1:
                        cls = segments[-2]
                    qualified = (
                        "::".join([*scope, raw]) if scope and not raw.startswith(scope[0] + "::") else raw
                    )
                text = _text(source, child)
                tags = [
                    (m.group(1), child.start_point[0] + 1 + text[: m.start()].count("\n"))
                    for m in REQUIREMENT_TAG.finditer(text)
                ]
                functions.append(
                    FunctionInfo(
                        name=name,
                        qualified=qualified,
                        class_name=cls,
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        text=text[:MAX_TEXT_CHARS],
                        doc=_leading_comments(child, source),
                        calls=_collect_calls(body, source),
                        requirement_tags=tags,
                        is_gtest_case=is_gtest,
                    )
                )
            elif (
                t
                in (
                    "declaration_list",
                    "field_declaration_list",
                    "linkage_specification",
                    "template_declaration",
                )
                or t.startswith("preproc_if")
                or t in ("preproc_else", "preproc_elif")
            ):
                visit(child, scope, class_name)

    visit(tree.root_node, [], None)
    return FileInfo(includes=includes, functions=functions, classes=classes, loc=source.count(b"\n") + 1)
