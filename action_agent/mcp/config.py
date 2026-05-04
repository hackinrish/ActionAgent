import sys
from pathlib import Path

STUBS_DIR = Path(__file__).parent / "stubs"

STUB_CONNECTIONS: dict = {
    "notion": {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(STUBS_DIR / "notion_stub.py")],
    },
    "jira": {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(STUBS_DIR / "jira_stub.py")],
    },
    "slack": {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(STUBS_DIR / "slack_stub.py")],
    },
}

# Phase 4: swap ACTIVE_CONNECTIONS to REAL_CONNECTIONS and fill .env API keys
REAL_CONNECTIONS: dict = {
    "notion": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@notionhq/notion-mcp-server"],
        "env": {},  # populated at runtime from settings
    },
    "jira": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@atlassian/jira-mcp"],
        "env": {},
    },
    "slack": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@slack/mcp-server"],
        "env": {},
    },
}

ACTIVE_CONNECTIONS = STUB_CONNECTIONS
