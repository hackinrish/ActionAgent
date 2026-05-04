from contextlib import asynccontextmanager
from typing import AsyncIterator, Any


@asynccontextmanager
async def get_mcp_tools() -> AsyncIterator[dict[str, list[Any]]]:
    """
    Phase 1: yields empty tool lists — dispatch nodes use direct stub calls.
    Phase 3: will use MultiServerMCPClient to load real MCP tools over stdio.
    """
    yield {"notion": [], "jira": [], "slack": []}
