from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jira-stub")

_counter: dict[str, int] = {"n": 0}


@mcp.tool()
def jira_create_issue(
    summary: str,
    description: str = "",
    assignee: str = "",
    due_date: str = "",
    priority: str = "Medium",
) -> dict:
    """Create a Jira issue for an action item."""
    _counter["n"] += 1
    key = f"PROJ-{_counter['n']}"
    return {
        "key": key,
        "id": str(_counter["n"]),
        "url": f"https://jira.example.com/browse/{key}",
        "status": "created",
    }


@mcp.tool()
def jira_update_issue(issue_key: str, fields: dict) -> dict:
    """Update a Jira issue."""
    return {"key": issue_key, "status": "updated"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
