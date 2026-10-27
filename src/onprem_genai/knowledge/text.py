"""Text normalisation for code-aware lexical retrieval."""

from __future__ import annotations

import re

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*|[0-9]+")

STOPWORDS = frozenset(
    (
        "a",
        "all",
        "an",
        "and",
        "any",
        "are",
        "as",
        "assert",
        "at",
        "auto",
        "be",
        "bool",
        "by",
        "can",
        "char",
        "component",
        "components",
        "const",
        "drv",
        "each",
        "eq",
        "expect",
        "f32",
        "f64",
        "false",
        "for",
        "from",
        "fw",
        "gt",
        "has",
        "have",
        "i16",
        "i32",
        "i64",
        "i8",
        "if",
        "in",
        "int",
        "into",
        "is",
        "it",
        "its",
        "lt",
        "may",
        "must",
        "ne",
        "no",
        "not",
        "null",
        "nullptr",
        "of",
        "on",
        "or",
        "os",
        "per",
        "return",
        "shall",
        "should",
        "signed",
        "static",
        "std",
        "svc",
        "test",
        "tester",
        "tests",
        "that",
        "the",
        "this",
        "to",
        "true",
        "u16",
        "u32",
        "u64",
        "u8",
        "unsigned",
        "ut",
        "via",
        "void",
        "was",
        "were",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
    )
)


def split_identifier(token: str) -> list[str]:
    """``runNominalDispatch`` -> [run, nominal, dispatch]; ``CMD_NO_OP`` -> [cmd, no, op]."""
    parts: list[str] = []
    for chunk in token.split("_"):
        if chunk:
            parts.extend(p for p in _CAMEL.split(chunk) if p)
    return [p.lower() for p in parts]


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN.findall(text):
        for part in split_identifier(tok):
            if len(part) < 2 and not part.isdigit():
                continue
            if keep_stopwords or part not in STOPWORDS:
                out.append(stem(part))
    return out


def stem(word: str) -> str:
    """Light English suffix stripping, sufficient to match requirement prose with code identifiers
    (``commands``/``command``, ``queues``/``queue``, ``dropped``/``drop``, ``matches``/``match``)."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "ches", "shes", "xes", "zes")):
        return word[:-2]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            if len(base) >= 2 and base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]
            return base
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word
