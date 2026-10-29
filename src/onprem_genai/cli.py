"""Command-line entry point: ``oge``.

Each command group lives behind an optional extra (``knowledge``, ``agent``, ``bench``, ...). A group whose
extra is not installed still appears in ``oge --help`` and says which extra to install, so a slim install
(the knowledge-graph image, a CI job that only downloads models) never fails on another group's imports.
"""

from __future__ import annotations

import importlib

import typer

from onprem_genai import __version__

app = typer.Typer(
    help="On-premise GenAI platform for embedded software engineering.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

# (command, module, attribute, extra that provides its dependencies)
GROUPS = (
    ("sizing", "onprem_genai.sizing.cli", "app", None),
    ("bench", "onprem_genai.bench.cli", "app", "bench"),
    ("eval", "onprem_genai.evalsuite.cli", "app", "eval"),
    ("knowledge", "onprem_genai.knowledge.cli", "app", "knowledge"),
    ("mcp", "onprem_genai.knowledge.cli", "mcp_app", "knowledge"),
    ("platform", "onprem_genai.platform.cli", "app", None),
    ("agent", "onprem_genai.agent.cli", "app", "agent,knowledge"),
    ("console", "onprem_genai.console.cli", "app", "console"),
)


def _unavailable(name: str, extra: str | None, missing: str) -> typer.Typer:
    hint = f"uv sync --extra {extra.replace(',', ' --extra ')}" if extra else "uv sync"
    sub = typer.Typer(help=f"(not installed: needs the '{extra}' extra)", add_completion=False)

    @sub.callback(invoke_without_command=True)
    def _explain() -> None:
        typer.echo(f"`oge {name}` needs the Python package '{missing}'. Install it with: {hint}", err=True)
        raise typer.Exit(2)

    return sub


for _name, _module, _attr, _extra in GROUPS:
    try:
        _sub = getattr(importlib.import_module(_module), _attr)
    except ModuleNotFoundError as exc:
        if not exc.name or exc.name.split(".")[0] == "onprem_genai":
            raise  # a bug in this package, not a missing optional dependency
        _sub = _unavailable(_name, _extra, exc.name.split(".")[0])
    app.add_typer(_sub, name=_name)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
