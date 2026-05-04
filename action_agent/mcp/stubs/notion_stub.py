from mcp.server.fastmcp import FastMCP

mcp = FastMCP("notion-stub")


@mcp.tool()
def notion_create_page(
    title: str,
    description: str,
    owner: str = "",
    deadline: str = "",
    priority: str = "medium",
) -> dict:
    """Create a Notion database page for an action item."""
    fake_id = f"notion-{abs(hash(title)) % 10000:04d}"
    return {
        "id": fake_id,
        "url": f"https://notion.so/{fake_id}",
        "status": "created",
    }


@mcp.tool()
def notion_query_database(database_id: str) -> dict:
    """Query a Notion database."""
    return {"results": [], "next_cursor": None}


if __name__ == "__main__":
    mcp.run(transport="stdio")
