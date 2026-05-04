from rich.table import Table
from rich.console import Console
from action_agent.models.schemas import ActionItem, DispatchResult


def build_action_items_table(items: list[ActionItem]) -> Table:
    table = Table(title="Action Items", show_lines=True)
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Description", min_width=30)
    table.add_column("Owner", style="green", width=20)
    table.add_column("Deadline", style="yellow", width=12)
    table.add_column("Priority", width=8)
    table.add_column("Status", width=22)

    for item in items:
        status = "[red]NEEDS CLARIFICATION[/red]" if item.needs_clarification else "[green]OK[/green]"
        table.add_row(
            item.id,
            item.description[:60],
            item.owner or "—",
            item.deadline or "—",
            item.priority.value,
            status,
        )
    return table


def print_dispatch_results(console: Console, results: list[DispatchResult]) -> None:
    if not results:
        return
    console.print("\n[bold]Dispatch Results:[/bold]")
    for r in results:
        icon = "✓" if r.success else "✗"
        color = "green" if r.success else "red"
        line = f"  [{color}]{icon} {r.tool.title()}[/{color}]"
        if r.item_id:
            line += f" — {r.item_id}"
        console.print(line)
