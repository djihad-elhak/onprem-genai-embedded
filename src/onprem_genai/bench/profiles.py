"""Traffic profiles that mimic how engineers use a code assistant.

Prompts are built from a real code corpus (F´ sources by default), so token statistics and prefix-sharing
behaviour resemble production traffic rather than lorem-ipsum. Requests are deterministic per index.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

CHARS_PER_TOKEN = 3.4  # typical for C/C++ with BPE tokenizers; exact counts come from server usage fields

CHAT_QUESTIONS = [
    "Explain what this component does and how its ports are used.",
    "List the error paths in this code and how each one is reported.",
    "Suggest unit tests that would cover the edge cases of the main handler.",
    "Refactor the longest function into smaller functions without changing behaviour.",
    "Write Doxygen documentation for the public methods.",
    "Is there any risk of integer overflow or out-of-bounds access here? Justify.",
]

SYSTEM_ENGINEER = (
    "You are a senior embedded C++ engineer working on flight software. Answer precisely and cite the "
    "functions you refer to."
)
SYSTEM_COMPLETION = (
    "You are a code completion engine. Continue the code exactly where it stops. Output code only."
)
SYSTEM_AGENT = (
    "You are an autonomous software-engineering agent. You can read files, run builds and run unit tests. "
    'Think step by step, then answer with the next action as JSON: {"tool": ..., "args": ...}.'
)


def load_corpus(root: Path, patterns: Iterable[str] = ("*.cpp", "*.hpp"), max_files: int = 400) -> list[str]:
    files: list[Path] = []
    for pat in patterns:
        files.extend(sorted(root.rglob(pat)))
    texts = []
    for f in sorted(set(files))[:max_files]:
        try:
            texts.append(f"// file: {f.relative_to(root)}\n{f.read_text(encoding='utf-8', errors='replace')}")
        except OSError:
            continue
    return texts


def synthetic_corpus(n_files: int = 50, seed: int = 0) -> list[str]:
    """Fallback C corpus for tests or when no checkout is available."""
    rng = random.Random(seed)
    out = []
    for f in range(n_files):
        funcs = []
        for i in range(rng.randint(5, 15)):
            funcs.append(
                f"static int32_t handler_{f}_{i}(int32_t x) {{\n"
                f"    if (x > {rng.randint(1, 999)}) {{ return x - {i}; }}\n"
                f"    return (x * {rng.randint(2, 9)}) ^ 0x{rng.randint(0, 0xFFFF):04X};\n}}\n"
            )
        out.append(f"// file: synthetic_{f}.c\n#include <stdint.h>\n" + "\n".join(funcs))
    return out


def _take(text: str, rng: random.Random, n_tokens: int) -> str:
    """~n_tokens of the concatenated corpus from a random line (wrapping around).

    Starting at a random line rather than at a file boundary keeps prompts distinct: with file-aligned starts,
    two requests drawing the same first file would share their whole prefix and hit the server's cache.
    """
    target = int(n_tokens * CHARS_PER_TOKEN)
    start = rng.randrange(len(text))
    start = text.find("\n", start) + 1  # 0 when there is no further newline: wrap to the start
    looped = text * ((start + target) // len(text) + 1)
    return looped[start : start + target]


@dataclass
class Profile:
    name: str
    description: str
    prompt_tokens: int
    max_tokens: int
    corpus: list[str] = field(repr=False)
    shared_prefix_tokens: int = 0
    seed: int = 1234
    _text: str = field(init=False, repr=False, default="")

    def __post_init__(self) -> None:
        self._text = "".join(self.corpus)

    def request(self, i: int) -> tuple[list[dict[str, str]], int]:
        rng = random.Random(self.seed * 1_000_003 + i)
        if self.name == "completion":
            code = _take(self._text, rng, self.prompt_tokens)
            cut = rng.randint(len(code) // 2, len(code))
            return [
                {"role": "system", "content": SYSTEM_COMPLETION},
                {"role": "user", "content": code[:cut]},
            ], self.max_tokens
        if self.name == "agent":
            # Identical long prefix for every request (repository context) -> exercises prefix caching.
            shared = _take(self._text, random.Random(self.seed), self.shared_prefix_tokens)
            tail = _take(self._text, rng, self.prompt_tokens - self.shared_prefix_tokens)
            return [
                {"role": "system", "content": SYSTEM_AGENT + "\n\nRepository context:\n" + shared},
                {"role": "user", "content": "Tool output:\n" + tail + "\n\nWhat is the next action?"},
            ], self.max_tokens
        context = _take(self._text, rng, self.prompt_tokens)
        question = CHAT_QUESTIONS[i % len(CHAT_QUESTIONS)]
        return [
            {"role": "system", "content": SYSTEM_ENGINEER},
            {"role": "user", "content": f"{context}\n\n{question}"},
        ], self.max_tokens


def make_profiles(corpus: list[str], scale: float = 1.0) -> dict[str, Profile]:
    """Standard profiles; ``scale`` shrinks prompt sizes for small-context deployments."""

    def s(n: int) -> int:
        return max(64, int(n * scale))

    return {
        "completion": Profile("completion", "inline completion in the editor", s(1500), 64, corpus),
        "chat": Profile("chat", "IDE chat with retrieved code context", s(3000), 400, corpus),
        "agent": Profile(
            "agent",
            "agent step with shared repository prefix",
            s(12000),
            250,
            corpus,
            shared_prefix_tokens=s(10000),
        ),
    }
