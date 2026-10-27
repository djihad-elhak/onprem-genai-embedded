"""Command-line entry point: ``oge``."""

from __future__ import annotations

import typer

from onprem_genai import __version__
from onprem_genai.bench.cli import app as bench_app
from onprem_genai.evalsuite.cli import app as eval_app
from onprem_genai.knowledge.cli import app as knowledge_app
from onprem_genai.knowledge.cli import mcp_app
from onprem_genai.platform.cli import app as platform_app
from onprem_genai.sizing.cli import app as sizing_app

app = typer.Typer(
    help="On-premise GenAI platform for embedded software engineering.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
app.add_typer(sizing_app, name="sizing")
app.add_typer(bench_app, name="bench")
app.add_typer(eval_app, name="eval")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(mcp_app, name="mcp")
app.add_typer(platform_app, name="platform")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
