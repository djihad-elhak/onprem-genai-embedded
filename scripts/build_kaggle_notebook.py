"""Build a Kaggle notebook (.ipynb) from its percent-format source (kaggle/*.py).

    python scripts/build_kaggle_notebook.py kaggle/01_benchmark.py
    python scripts/build_kaggle_notebook.py kaggle/01_benchmark.py --standalone --out dist/01_benchmark.ipynb
    python scripts/build_kaggle_notebook.py kaggle/01_benchmark.py --set 'STAGES=["serving", "agent"]'

``--standalone`` embeds the wheel of this package (built from the working tree) so the notebook runs without
access to the repository; the commit is recorded (suffix ``-dirty`` when the tree has uncommitted changes).
``--set NAME=VALUE`` replaces a one-line top-level parameter (``NAME = ...``) with a Python literal, e.g. to
re-run a subset of stages.
"""

from __future__ import annotations

import argparse
import ast
import base64
import re
import subprocess
import tempfile
from pathlib import Path

import jupytext

ROOT = Path(__file__).resolve().parents[1]
KAGGLE_METADATA = {
    "kaggle": {
        "accelerator": "nvidiaTeslaT4",
        "isGpuEnabled": True,
        "isInternetEnabled": True,
        "language": "python",
        "sourceType": "notebook",
    },
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def build_wheel() -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["uv", "build", "--wheel", "-q", "-o", tmp], cwd=ROOT, check=True)
        wheel = next(Path(tmp).glob("onprem_genai_embedded-*.whl"))
        data = base64.b64encode(wheel.read_bytes()).decode()
    commit = _git("rev-parse", "HEAD") + (
        "-dirty" if _git("status", "--porcelain", "--untracked-files=no") else ""
    )
    return data, commit


def set_parameter(nb, item: str) -> None:
    """Replace the one-line definition ``NAME = ...`` of a top-level parameter with ``NAME = VALUE``."""
    name, _, value = item.partition("=")
    name, value = name.strip(), value.strip()
    ast.literal_eval(value)  # only literals: the notebook stays a plain, reviewable script
    rx = re.compile(rf"^{re.escape(name)} = [^\n]*$", re.MULTILINE)
    cells = [c for c in nb.cells if c.cell_type == "code" and rx.search(c.source)]
    if len(cells) != 1 or len(rx.findall(cells[0].source)) != 1:
        raise SystemExit(f"parameter {name!r} must be defined once, on one line")
    cells[0].source = rx.sub(f"{name} = {value}  # set by build_kaggle_notebook.py --set", cells[0].source)
    print(f"set {name} = {value}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--standalone", action="store_true")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="override a parameter")
    args = ap.parse_args()
    nb = jupytext.read(args.source)
    nb.metadata = {
        **KAGGLE_METADATA,
        "jupytext": {
            "cell_metadata_filter": "-all",
            "main_language": "python",
            "notebook_metadata_filter": "-all",
        },
    }
    for i, cell in enumerate(nb.cells):  # stable ids: rebuilding an unchanged source gives an identical file
        cell["id"] = f"cell-{i:02d}"
    for item in args.set:
        set_parameter(nb, item)
    if args.standalone:
        data, commit = build_wheel()
        cell = next(c for c in nb.cells if c.cell_type == "code" and "WHEEL_B64 = None" in c.source)
        cell.source = cell.source.replace("WHEEL_B64 = None", f'WHEEL_B64 = "{data}"').replace(
            "WHEEL_COMMIT = None", f'WHEEL_COMMIT = "{commit}"'
        )
        print(f"embedded wheel: {len(data) // 1024} KiB base64, commit {commit}")
    out = args.out or args.source.with_suffix(".ipynb")
    out.parent.mkdir(parents=True, exist_ok=True)
    jupytext.write(nb, out, fmt="ipynb")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
