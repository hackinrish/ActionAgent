from contextlib import asynccontextmanager
from typing import AsyncIterator, Any
from langchain_mcp_adapters.client import MultiServerMCPClient
from action_agent.mcp.config import ACTIVE_CONNECTIONS


@asynccontextmanager
async def get_mcp_tools() -> AsyncIterator[dict[str, list[Any]]]:
    """
    Async context manager yielding {server_name: [LangChain tools]}.

    Usage:
        async with get_mcp_tools() as tools:
            notion_tools = tools["notion"]
    """
    client = MultiServerMCPClient(ACTIVE_CONNECTIONS)
    tools_by_server: dict[str, list[Any]] = {}
    for server_name in ACTIVE_CONNECTIONS:
        tools_by_server[server_name] = await client.get_tools(server_name=server_name)
    yield tools_by_server
