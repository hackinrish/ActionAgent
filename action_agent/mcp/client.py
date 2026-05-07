from contextlib import asynccontextmanager
from typing import AsyncIterator, Any
from langchain_mcp_adapters.client import MultiServerMCPClient
from action_agent.mcp.config import get_active_connections


@asynccontextmanager
async def get_mcp_tools() -> AsyncIterator[dict[str, list[Any]]]:
    """
    Async context manager yielding {server_name: [LangChain tools]}.

    Selects stub or real MCP servers based on settings.use_stub_mcp.
    Validates that required env keys are present before connecting in real mode.

    Usage:
        async with get_mcp_tools() as tools:
            notion_tools = tools["notion"]
    """
    from action_agent.config import settings, validate_real_mcp_keys

    validate_real_mcp_keys(settings)
    connections = get_active_connections(settings)

    client = MultiServerMCPClient(connections)
    tools_by_server: dict[str, list[Any]] = {}
    for server_name in connections:
        tools_by_server[server_name] = await client.get_tools(server_name=server_name)
    yield tools_by_server
