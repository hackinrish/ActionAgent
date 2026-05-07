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

ACTIVE_CONNECTIONS = STUB_CONNECTIONS  # legacy — prefer get_active_connections(settings)


def get_active_connections(settings) -> dict:
    """
    Return the correct MCP connection set based on settings.use_stub_mcp.
    When use_stub_mcp=False, REAL_CONNECTIONS env dicts are populated from settings.
    """
    if settings.use_stub_mcp:
        return STUB_CONNECTIONS

    return {
        "notion": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@notionhq/notion-mcp-server"],
            "env": {
                "NOTION_API_KEY":    settings.notion_api_key,
                "NOTION_DATABASE_ID": settings.notion_database_id,
            },
        },
        "jira": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@atlassian/jira-mcp"],
            "env": {
                "JIRA_URL":       settings.jira_url,
                "JIRA_EMAIL":     settings.jira_email,
                "JIRA_API_TOKEN": settings.jira_api_token,
                "JIRA_PROJECT_KEY": settings.jira_project_key,
            },
        },
        "slack": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@slack/mcp-server"],
            "env": {
                "SLACK_BOT_TOKEN": settings.slack_bot_token,
                "SLACK_CHANNEL":   settings.slack_channel,
            },
        },
    }
