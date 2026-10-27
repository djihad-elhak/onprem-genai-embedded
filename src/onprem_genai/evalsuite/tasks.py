"""Evaluation tasks: loading and validation of the on-disk task format.

Each task lives in ``tasks/<id>/`` with a ``task.yaml`` and C sources:

* ``generate``  – ``task.h`` (interface), ``tests.c`` (hidden), ``solution.c`` (reference, never shown)
* ``testgen``   – ``task.h``, ``impl.c`` (shown), ``mutants/*.c`` (hidden), ``ref_tests.c`` (reference tests)
* ``refactor``  – ``task.h``, ``original.c`` (shown), ``tests.c`` (hidden), ``solution.c`` (reference)
* ``document``  – ``task.h``, ``original.c`` (shown, undocumented), ``tests.c`` (hidden), ``solution.c``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from importlib import resources
from pathlib import Path

import yaml


class Category(StrEnum):
    GENERATE = "generate"
    TESTGEN = "testgen"
    REFACTOR = "refactor"
    DOCUMENT = "document"


@dataclass
class Task:
    id: str
    category: Category
    title: str
    description: str
    root: Path
    domain: str = ""
    difficulty: str = "medium"
    banned: list[str] = field(default_factory=list)

    @property
    def header(self) -> str:
        return (self.root / "task.h").read_text(encoding="utf-8")

    def source(self, name: str) -> str:
        return (self.root / name).read_text(encoding="utf-8")

    @property
    def mutants(self) -> list[Path]:
        return sorted((self.root / "mutants").glob("*.c"))


DEFAULT_BANNED = ["malloc", "calloc", "realloc", "free", "printf", "fprintf", "puts", "exit", "abort"]


def tasks_dir() -> Path:
    return Path(str(resources.files("onprem_genai.evalsuite").joinpath("tasks")))


def include_dir() -> Path:
    return Path(str(resources.files("onprem_genai.evalsuite").joinpath("include")))


def load_tasks(root: Path | None = None, categories: list[str] | None = None) -> list[Task]:
    base = root or tasks_dir()
    out = []
    for meta in sorted(base.glob("*/task.yaml")):
        raw = yaml.safe_load(meta.read_text(encoding="utf-8"))
        task = Task(
            id=raw["id"],
            category=Category(raw["category"]),
            title=raw["title"],
            description=raw["description"].strip(),
            root=meta.parent,
            domain=raw.get("domain", ""),
            difficulty=raw.get("difficulty", "medium"),
            banned=raw.get("banned", DEFAULT_BANNED),
        )
        if task.id != meta.parent.name:
            raise ValueError(f"task id {task.id!r} does not match directory {meta.parent.name!r}")
        if categories and task.category.value not in categories:
            continue
        out.append(task)
    return out
