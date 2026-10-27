"""Prompt construction and code extraction for the evaluation suite.

Prompts are deliberately plain (one system message, one user message, no few-shot examples) so that the
comparison measures the models, not prompt engineering. The exact templates are part of the suite fingerprint.
"""

from __future__ import annotations

import re

from onprem_genai.evalsuite.tasks import Category, Task

SYSTEM_PROMPT = (
    "You are a senior embedded software engineer working on safety-critical radio and flight software. "
    "You write portable C99 that compiles cleanly with -Wall -Wextra -Wpedantic, uses no dynamic memory "
    "allocation, no standard I/O in production code and no goto. "
    "Answer with exactly one fenced code block (```c ... ```) containing the complete requested file, "
    "and nothing else."
)

TEST_FRAMEWORK_DOC = """\
oge_test.h (already available on the include path) provides:
  CHECK(cond)            boolean check
  CHECK_EQ_U(a, b)       unsigned comparison, prints both values on failure
  CHECK_EQ_I(a, b)       signed comparison
  CHECK_MEM(a, b, n)     byte-wise comparison of n bytes
  return OGE_REPORT();   at the end of main(): prints counts, exit code 1 on any failure"""


def _block(name: str, code: str) -> str:
    return f"{name}:\n```c\n{code.strip()}\n```"


def build_messages(task: Task) -> list[dict[str, str]]:
    """Chat messages for one task (OpenAI chat-completions format)."""
    head = f"Task: {task.title}\n\n{task.description}\n\n"
    if task.category is Category.GENERATE:
        body = (
            f"{_block('task.h', task.header)}\n\n"
            "Write solution.c implementing every function declared in task.h. "
            'The file must start with #include "task.h". Hidden unit tests will be compiled against it.'
        )
    elif task.category is Category.TESTGEN:
        body = (
            f"{TEST_FRAMEWORK_DOC}\n\n{_block('task.h', task.header)}\n\n"
            f"{_block('impl.c', task.source('impl.c'))}\n\n"
            "Write tests.c: a complete unit-test program for the specification in task.h. "
            'It must include "task.h" and "oge_test.h", define main() ending with return OGE_REPORT();, '
            "pass on impl.c, and fail on any implementation that deviates from the specification."
        )
    elif task.category is Category.REFACTOR:
        body = (
            f"{_block('task.h', task.header)}\n\n{_block('original.c', task.source('original.c'))}\n\n"
            "Return the complete refactored file (it replaces original.c)."
        )
    else:
        body = (
            f"{_block('task.h', task.header)}\n\n{_block('original.c', task.source('original.c'))}\n\n"
            "Return the complete documented file (it replaces original.c)."
        )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": head + body}]


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+\-]*)[^\n]*\n(.*?)```", re.DOTALL)
_C_LANGS = {"c", "c99", "h", "cpp", "c++", "cc"}


def strip_reasoning(text: str) -> str:
    """Remove ``<think>`` blocks (reasoning models that inline their chain of thought in the content)."""
    text = _THINK.sub("", text)
    if "</think>" in text:  # opening tag consumed by the chat template: keep what follows the last close tag
        text = text.rsplit("</think>", 1)[1]
    return text


def extract_code(text: str) -> str:
    """The code file contained in a model answer.

    Prefers the longest fenced block tagged as C; falls back to the longest fenced block of any language, then
    to the whole answer (models that ignore the formatting instruction).
    """
    text = strip_reasoning(text or "")
    blocks = [(lang.lower(), code) for lang, code in _FENCE.findall(text)]
    if not blocks and "```" in text:  # unterminated fence (answer cut by max_tokens): take what is there
        _, _, rest = text.partition("```")
        blocks = [("", rest.split("\n", 1)[1] if "\n" in rest else "")]
    if not blocks:
        return text.strip() + "\n"
    c_blocks = [b for b in blocks if b[0] in _C_LANGS]
    return max(c_blocks or blocks, key=lambda b: len(b[1]))[1].strip() + "\n"
