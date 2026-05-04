from mcp.server.fastmcp import FastMCP

mcp = FastMCP("slack-stub")


@mcp.tool()
def slack_post_message(channel: str, text: str) -> dict:
    """Post a message to a Slack channel."""
    return {
        "ok": True,
        "ts": "1234567890.123456",
        "channel": channel,
    }


@mcp.tool()
def slack_get_channel_id(channel_name: str) -> dict:
    """Get the ID of a Slack channel by name."""
    return {"ok": True, "channel_id": f"C{abs(hash(channel_name)) % 100000:05d}"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
