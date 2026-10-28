"""Turn a model answer into a policy-checked edit of a component's unit tests.

The model writes only two things: Tester member function definitions and gtest ``TEST()`` cases. Everything
else
is done here, deterministically: declarations are derived from the definitions, code is inserted at structural
anchors found with tree-sitter, the requirement tag is enforced, and the edit is confined to the three test
files
(``<C>Tester.hpp``, ``<C>Tester.cpp``, ``<C>TestMain.cpp``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from onprem_genai.agent.fprime import Component, test_cases, tester_methods
from onprem_genai.knowledge.fprime.cpp import cpp_parser, parse_cpp

NOT_TESTABLE = re.compile(r"^\s*NOT[_ ]TESTABLE\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+\-]*)[ \t]*([A-Za-z_]*)[^\n]*\n(.*?)```", re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r'REQUIREMENT\s*\(\s*"([^"]+)"\s*\)')
_ASSERTION = re.compile(r"\b(?:ASSERT|EXPECT)_\w*\s*\(")
BANNED = {
    r"\bsystem\s*\(": "system()",
    r"\bpopen\s*\(": "popen()",
    r"\bfork\s*\(": "fork()",
    r"\bexec[lv]p?e?\s*\(": "exec*()",
    r"\bexit\s*\(": "exit()",
    r"\babort\s*\(": "abort()",
    r"\bGTEST_SKIP\b": "GTEST_SKIP",
    r"\bDISABLED_": "disabled tests",
    r"^\s*#\s*(?:define|undef|pragma)\b": "preprocessor definitions",
    r"\basm\b|__asm__": "inline assembly",
    r"\bstd::thread\b|\bpthread_create\b": "threads",
}
MAX_NEW_LINES = 400


class PatchError(ValueError):
    """The answer cannot be applied; the message is fed back to the model."""


@dataclass
class MemberDef:
    name: str
    declaration: str
    text: str


@dataclass
class TestPatch:
    includes: list[str] = field(default_factory=list)
    definitions: list[MemberDef] = field(default_factory=list)
    test_block: str = ""
    test_names: list[str] = field(default_factory=list)  # Suite.Name

    @property
    def gtest_filter(self) -> str:
        return ":".join(self.test_names)

    @property
    def method_names(self) -> list[str]:
        return [d.name for d in self.definitions]


@dataclass
class Answer:
    tester_code: str = ""
    main_code: str = ""
    not_testable: str | None = None


# ------------------------------------------------------------------------------------------- parsing
def parse_answer(text: str) -> Answer:
    text = _THINK.sub("", text or "")
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    blocks = [(lang.lower(), label.lower(), code) for lang, label, code in _FENCE.findall(text)]
    if not blocks and (m := NOT_TESTABLE.search(text)):
        return Answer(not_testable=m.group(1).strip())
    ans = Answer()
    for _lang, label, code in blocks:
        if label == "main" or (not label and re.search(r"^\s*TEST\s*\(", code, re.MULTILINE)):
            ans.main_code += code
        elif label == "tester" or not label:
            ans.tester_code += code
    if not ans.tester_code and not ans.main_code and (m := NOT_TESTABLE.search(text)):
        return Answer(not_testable=m.group(1).strip())
    return ans


def _member_definitions(code: str, cls: str) -> tuple[list[MemberDef], list[str]]:
    """Function definitions qualified with ``cls`` (declaration derived from the definition) + #includes."""
    src = code.encode()
    tree = cpp_parser().parse(src)
    includes = re.findall(r"^\s*#\s*include\s*[<\"][^>\"]+[>\"]", code, re.MULTILINE)
    defs: list[MemberDef] = []
    stray: list[str] = []

    def visit(node) -> None:
        if node.type == "function_definition":
            body = node.child_by_field_name("body")
            head = src[node.start_byte : body.start_byte if body else node.end_byte].decode().strip()
            text = src[node.start_byte : node.end_byte].decode()
            m = re.search(rf"\b{re.escape(cls)}\s*::\s*(~?\w+)\s*\(", head)
            if not m:
                name = re.search(r"(\w+)\s*\(", head)
                stray.append(name.group(1) if name else head[:60])
                return
            decl = re.sub(rf"\b{re.escape(cls)}\s*::\s*", "", head, count=1)
            decl = re.sub(r"\s*\boverride\b", "", decl).strip()
            defs.append(MemberDef(m.group(1), decl + ";", text.strip()))
            return
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    if stray:
        raise PatchError(
            f"functions {stray} are not members of {cls}: define every function as `{cls}::name(...)` "
            "(helpers too), or put the code inside the test method"
        )
    return defs, [i.strip() for i in includes]


def build_patch(answer: Answer, c: Component, req_id: str) -> TestPatch:
    """Validate an answer against the component and the policy (PatchError carries an actionable message)."""
    if not answer.tester_code.strip():
        raise PatchError(
            f"missing the ```cpp tester``` block with {c.tester_class} member function definitions"
        )
    if not answer.main_code.strip():
        raise PatchError("missing the ```cpp main``` block with the TEST() case(s)")
    defs, includes = _member_definitions(answer.tester_code, c.tester_class)
    if not defs:
        raise PatchError(f"no member function definitions of {c.tester_class} found in the tester block")
    existing_methods = tester_methods(c)
    clash = sorted({d.name for d in defs} & set(existing_methods))
    if clash:
        raise PatchError(f"{c.tester_class} already defines {clash}: choose new method names")
    if len({d.name for d in defs}) != len(defs):
        raise PatchError("overloaded or duplicated method names are not allowed: use distinct names")

    main = answer.main_code.strip()
    cases = [f for f in parse_cpp(main.encode()).functions if f.is_gtest_case]
    if not cases or re.search(r"\b(TEST_F|TEST_P|TYPED_TEST)\s*\(", main):
        raise PatchError("the main block must contain plain gtest TEST(Suite, Name) { ... } cases only")
    other = parse_cpp(main.encode()).functions
    if len(other) != len(cases) or re.search(r"\bint\s+main\s*\(", main):
        raise PatchError("the main block must contain only TEST() cases (no main(), no helper functions)")
    names = [f.name for f in cases]
    dup = sorted(set(names) & set(test_cases(c)))
    if dup:
        raise PatchError(f"test case(s) {dup} already exist: choose new TEST(Suite, Name) names")
    if not any(re.search(rf"\.\s*{re.escape(d.name)}\s*\(", main) for d in defs):
        raise PatchError(f"the TEST() case must call one of the new {c.tester_class} methods")

    new_code = answer.tester_code + "\n" + main
    for pattern, what in BANNED.items():
        if re.search(pattern, new_code, re.MULTILINE):
            raise PatchError(f"{what} is not allowed in unit tests")
    if len(new_code.splitlines()) > MAX_NEW_LINES:
        raise PatchError(f"the answer exceeds {MAX_NEW_LINES} lines: write one focused test")
    if not _ASSERTION.search(new_code):
        raise PatchError(
            "the test has no assertion: check observable outputs with ASSERT_* / EXPECT_* macros"
        )
    tags = set(_TAG.findall(new_code))
    if tags - {req_id}:
        raise PatchError(f'only REQUIREMENT("{req_id}") may be tagged, found {sorted(tags)}')
    if not tags:  # enforce the traceability tag in the first method the test calls
        called = next(d for d in defs if re.search(rf"\.\s*{re.escape(d.name)}\s*\(", main))
        called.text = re.sub(r"\{", f'{{\n    REQUIREMENT("{req_id}");', called.text, count=1)
    return TestPatch(includes, defs, main + "\n", names)


# ------------------------------------------------------------------------------------------- applying
def _class_body_end(hpp: str, cls: str) -> int:
    src = hpp.encode()
    tree = cpp_parser().parse(src)
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in ("class_specifier", "struct_specifier"):
            name = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            if name is not None and body is not None and src[name.start_byte : name.end_byte].decode() == cls:
                closing = src.rindex(b"}", body.start_byte, body.end_byte)
                return len(src[:closing].decode())
        stack.extend(node.children)
    raise PatchError(f"class {cls} not found in the tester header")


def render(c: Component, patch: TestPatch, req_id: str) -> dict[str, str]:
    """New contents of the three test files (pure function of the current files and the patch)."""
    hpp = c.tester_hpp.read_text(encoding="utf-8")
    cpp = c.tester_cpp.read_text(encoding="utf-8")
    main = c.test_main.read_text(encoding="utf-8")

    at = _class_body_end(hpp, c.tester_class)
    decls = "".join(f"    {d.declaration}\n" for d in patch.definitions)
    hpp = hpp[:at] + f"\n  public:\n    //! Tests generated for requirement {req_id}\n{decls}" + hpp[at:]

    methods = tester_methods(c)
    lines = cpp.splitlines(keepends=True)
    insert_after = max(end for _, end, _ in methods.values()) if methods else len(lines)
    body = "\n".join(d.text for d in patch.definitions)
    block = f"\n// Requirement {req_id}\n{body}\n"
    lines.insert(insert_after, block)
    cpp = "".join(lines)
    includes = list(patch.includes)
    if "UnitTest.hpp" not in cpp and "UnitTest.hpp" not in hpp:
        includes.append('#include "Fw/Test/UnitTest.hpp"')
    includes = [i for i in dict.fromkeys(includes) if i not in cpp]
    if includes:
        last = [m.end() for m in re.finditer(r"^\s*#\s*include[^\n]*\n", cpp, re.MULTILINE)]
        pos = last[-1] if last else 0
        cpp = cpp[:pos] + "".join(f"{i}\n" for i in includes) + cpp[pos:]

    m = re.search(r"^int\s+main\s*\(", main, re.MULTILINE)
    test_text = f"// Requirement {req_id}\n{patch.test_block}\n"
    main = main[: m.start()] + test_text + main[m.start() :] if m else main.rstrip("\n") + "\n\n" + test_text
    return {str(c.tester_hpp): hpp, str(c.tester_cpp): cpp, str(c.test_main): main}


def apply(c: Component, patch: TestPatch, req_id: str) -> None:
    for path, text in render(c, patch, req_id).items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
