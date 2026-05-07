from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(
    name="debrief",
    help="Meeting Debrief Agent — extract action items from meeting transcripts.",
)
console = Console()


@app.command()
def run(
    transcript: Path = typer.Argument(..., help="Path to meeting transcript .txt file"),
    team: Optional[str] = typer.Option(
        None, "--team", "-t",
        help="Comma-separated team member names (overrides .env TEAM_MEMBERS)",
    ),
    stub: bool = typer.Option(
        True, "--stub/--no-stub",
        help="Use stub MCP servers (no external API keys required)",
    ),
):
    """Process a meeting transcript and push action items to Notion, Jira, and Slack."""
    asyncio.run(_run(transcript, team, stub))


async def _run(transcript_path: Path, team_override: Optional[str], use_stubs: bool) -> None:
    from action_agent.config import settings
    from action_agent.graph.builder import build_graph
    from action_agent.utils.formatting import build_action_items_table, print_dispatch_results

    settings.use_stub_mcp = use_stubs

    if not transcript_path.exists():
        console.print(f"[red]File not found: {transcript_path}[/red]")
        raise typer.Exit(1)

    transcript_text = transcript_path.read_text()
    team_members = (
        [m.strip() for m in team_override.split(",") if m.strip()]
        if team_override
        else settings.team_members
    )

    from action_agent.mcp.client import get_mcp_tools

    graph = build_graph()
    initial_state = {
        "transcript": transcript_text,
        "team_members": team_members,
        "messages": [],
        "summary": None,
        "raw_action_items": [],
        "assigned_action_items": [],
        "validation_result": None,
        "validation_attempts": 0,
        "dispatch_results": [],
        "error": None,
        "status": "running",
    }

    console.print(Panel("[bold green]Meeting Debrief Agent[/bold green]", expand=False))

    async with get_mcp_tools() as mcp_tools:
        config = {"configurable": {"thread_id": "cli-run-001", "mcp_tools": mcp_tools}}
        final_state: dict = {}
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            for node_name, updates in event.items():
                console.print(f"  [dim]✓ {node_name}[/dim]")
                if isinstance(updates, dict):
                    final_state.update(updates)

    merged = {**initial_state, **final_state}
    _print_results(merged)


def _print_results(state: dict) -> None:
    from action_agent.utils.formatting import build_action_items_table, print_dispatch_results

    if state.get("summary"):
        s = state["summary"]
        console.print(f"\n[bold]Meeting:[/bold] {s.title}")
        if s.participants:
            console.print(f"[bold]Participants:[/bold] {', '.join(s.participants)}")
        console.print(f"\n{s.summary}\n")

    vr = state.get("validation_result")
    all_items = []
    if vr:
        all_items = vr.valid_items + vr.flagged_items

    if not all_items:
        console.print("[yellow]No action items found.[/yellow]")
    else:
        console.print(build_action_items_table(all_items))

    print_dispatch_results(console, state.get("dispatch_results", []))


if __name__ == "__main__":
    app()
