"""Parse requirement tables from F´ software design documents (``docs/sdd.md``).

F´ SDDs list requirements in Markdown tables whose header starts with ``Requirement | Description`` and
usually includes a verification-method column. Both pipe styles (with and without leading ``|``) occur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REQ_ID = re.compile(r"^[A-Z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*-\d{2,4}[a-z]?$")
_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_INLINE = re.compile(r"[`*]")


@dataclass(frozen=True)
class RequirementRow:
    req_id: str
    text: str
    verification: str
    rationale: str
    source_file: str
    line: int


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _clean(cell: str) -> str:
    return _INLINE.sub("", cell).strip()


def parse_requirement_tables(markdown: str, source_file: str = "") -> list[RequirementRow]:
    """Extract requirement rows from every Markdown table whose first column holds requirement IDs.

    Detection is content-based (header names vary across F´ SDDs: ``Requirement``, ``Name``, ``ID``...);
    the description is the column named *description* (else the second column), and verification /
    rationale columns are matched by name (``verification``, ``validation``, ``method``; ``rationale``).
    """
    lines = markdown.splitlines()
    rows: list[RequirementRow] = []
    i = 0
    while i + 1 < len(lines):
        if "|" not in lines[i] or not _SEPARATOR.match(lines[i + 1].strip()):
            i += 1
            continue
        names = [_clean(h).lower() for h in _cells(lines[i])]
        desc_col = next((k for k, n in enumerate(names) if "description" in n), 1)
        ver_col = next(
            (k for k, n in enumerate(names) if n.startswith(("verification", "validation", "method"))), None
        )
        rat_col = next((k for k, n in enumerate(names) if n.startswith("rationale")), None)
        i += 2
        while i < len(lines) and "|" in lines[i] and lines[i].strip():
            cells = _cells(lines[i])
            req_id = _clean(cells[0]) if cells else ""
            if REQ_ID.match(req_id) and len(cells) > desc_col:
                rows.append(
                    RequirementRow(
                        req_id=req_id,
                        text=_clean(cells[desc_col]),
                        verification=_clean(cells[ver_col])
                        if ver_col is not None and ver_col < len(cells)
                        else "",
                        rationale=_clean(cells[rat_col])
                        if rat_col is not None and rat_col < len(cells)
                        else "",
                        source_file=source_file,
                        line=i + 1,
                    )
                )
            i += 1
    return rows


def parse_sdd(path: Path, root: Path) -> list[RequirementRow]:
    return parse_requirement_tables(
        path.read_text(encoding="utf-8", errors="replace"), str(path.relative_to(root))
    )
