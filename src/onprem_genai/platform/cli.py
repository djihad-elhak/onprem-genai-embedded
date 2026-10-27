"""`oge platform ...` commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from onprem_genai.platform.smoke import main_json, run_smoke

app = typer.Typer(help="Operate and verify the deployed platform.", no_args_is_help=True)


@app.command("smoke")
def smoke(
    llm_url: Annotated[str | None, typer.Option(envvar="OGE_LLM_URL")] = None,
    embed_url: Annotated[str | None, typer.Option(envvar="OGE_EMBED_URL")] = None,
    mcp_url: Annotated[
        str | None, typer.Option(envvar="OGE_MCP_URL", help="e.g. http://host:8765/mcp")
    ] = None,
    expect_offline: Annotated[bool, typer.Option(help="Fail if any outbound connection succeeds")] = False,
    api_key: Annotated[str | None, typer.Option(envvar="OGE_API_KEY")] = None,
    wait: Annotated[float, typer.Option(help="Seconds to wait for /health before testing")] = 0.0,
    out: Path | None = None,
) -> None:
    """Check LLM, embeddings, knowledge MCP server and (optionally) that egress is blocked."""
    report = run_smoke(
        llm_url=llm_url,
        embed_url=embed_url,
        mcp_url=mcp_url,
        expect_offline=expect_offline,
        api_key=api_key,
        wait_s=wait,
    )
    text = main_json(report)
    typer.echo(text)
    if out:
        out.write_text(text, encoding="utf-8")
    raise typer.Exit(0 if report["passed"] else 1)
