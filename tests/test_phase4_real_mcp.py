"""
Phase 4 tests — real MCP connections and credential validation.

These tests are written BEFORE the implementation exists (TDD).
They will fail with ImportError initially and turn GREEN once the
following are implemented:
  - get_active_connections(settings) in action_agent/mcp/config.py
  - validate_real_mcp_keys(settings) in action_agent/config.py

Specs covered:
  1.  get_active_connections returns STUB_CONNECTIONS when use_stub_mcp=True
  2.  get_active_connections returns REAL_CONNECTIONS structure when use_stub_mcp=False
  3.  REAL_CONNECTIONS env dicts are populated from settings values
  4.  validate_real_mcp_keys raises ValueError naming all missing keys
  5.  validate_real_mcp_keys passes silently when all keys are present
  6.  validate_real_mcp_keys error lists ONLY the missing keys
  7.  REAL_CONNECTIONS use "npx" as command (not sys.executable)
  8.  (integration) notion_create_page creates a page with a notion.so URL
  9.  (integration) jira_create_issue creates an issue with the correct key prefix
  10. (integration) slack_post_message returns ok=True
  11. (regression) stub mode still returns STUB_CONNECTIONS with all tool names
"""

import json
import os
import pytest

# ---------------------------------------------------------------------------
# Spec 1
# ---------------------------------------------------------------------------

def test_get_active_connections_returns_stub_when_use_stub_mcp_true():
    """Spec 1: get_active_connections(settings) returns STUB_CONNECTIONS when
    settings.use_stub_mcp is True."""
    from action_agent.mcp.config import get_active_connections, STUB_CONNECTIONS
    from action_agent.config import Settings

    settings = Settings(use_stub_mcp=True)
    result = get_active_connections(settings)
    assert result == STUB_CONNECTIONS


# ---------------------------------------------------------------------------
# Spec 2
# ---------------------------------------------------------------------------

def test_get_active_connections_returns_real_structure_when_use_stub_mcp_false():
    """Spec 2: get_active_connections(settings) returns a dict containing
    notion, jira, and slack server entries when settings.use_stub_mcp is False."""
    from action_agent.mcp.config import get_active_connections
    from action_agent.config import Settings

    settings = Settings(
        use_stub_mcp=False,
        notion_api_key="fake-notion-key",
        notion_database_id="fake-db-id",
        jira_url="https://fake.atlassian.net",
        jira_email="fake@example.com",
        jira_api_token="fake-jira-token",
        jira_project_key="FAKE",
        slack_bot_token="xoxb-fake-slack-token",
    )
    result = get_active_connections(settings)

    assert "notion" in result, "Expected 'notion' server in REAL_CONNECTIONS"
    assert "jira" in result, "Expected 'jira' server in REAL_CONNECTIONS"
    assert "slack" in result, "Expected 'slack' server in REAL_CONNECTIONS"


# ---------------------------------------------------------------------------
# Spec 3
# ---------------------------------------------------------------------------

def test_get_active_connections_real_env_dicts_populated_from_settings():
    """Spec 3: The env sub-dicts in the REAL_CONNECTIONS returned by
    get_active_connections are populated with actual values from settings
    (e.g. env["NOTION_API_KEY"] equals settings.notion_api_key)."""
    from action_agent.mcp.config import get_active_connections
    from action_agent.config import Settings

    settings = Settings(
        use_stub_mcp=False,
        notion_api_key="my-notion-key",
        notion_database_id="my-db-id",
        jira_url="https://my.atlassian.net",
        jira_email="me@example.com",
        jira_api_token="my-jira-token",
        jira_project_key="MYP",
        slack_bot_token="xoxb-my-slack-token",
    )
    result = get_active_connections(settings)

    notion_env = result["notion"].get("env", {})
    assert notion_env.get("NOTION_API_KEY") == "my-notion-key", (
        "notion env['NOTION_API_KEY'] should equal settings.notion_api_key"
    )

    jira_env = result["jira"].get("env", {})
    assert jira_env.get("JIRA_URL") == "https://my.atlassian.net", (
        "jira env['JIRA_URL'] should equal settings.jira_url"
    )

    slack_env = result["slack"].get("env", {})
    assert slack_env.get("SLACK_BOT_TOKEN") == "xoxb-my-slack-token", (
        "slack env['SLACK_BOT_TOKEN'] should equal settings.slack_bot_token"
    )


# ---------------------------------------------------------------------------
# Spec 4
# ---------------------------------------------------------------------------

def test_validate_real_mcp_keys_raises_when_keys_blank():
    """Spec 4: validate_real_mcp_keys(settings) raises ValueError when
    use_stub_mcp=False and required keys are blank. The error message must
    name all missing keys."""
    from action_agent.config import Settings, validate_real_mcp_keys

    required_keys = [
        "NOTION_API_KEY",
        "NOTION_DATABASE_ID",
        "JIRA_URL",
        "JIRA_EMAIL",
        "JIRA_API_TOKEN",
        "JIRA_PROJECT_KEY",
        "SLACK_BOT_TOKEN",
    ]

    # All required fields left blank (defaults)
    settings = Settings(use_stub_mcp=False)

    with pytest.raises(ValueError) as exc_info:
        validate_real_mcp_keys(settings)

    error_text = str(exc_info.value)
    for key in required_keys:
        assert key in error_text, (
            f"Expected missing key '{key}' to appear in ValueError message, "
            f"got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# Spec 5
# ---------------------------------------------------------------------------

def test_validate_real_mcp_keys_passes_when_all_keys_present(monkeypatch):
    """Spec 5: validate_real_mcp_keys(settings) passes silently (no exception)
    when all required keys have non-empty values. Fake values are injected via
    monkeypatch so no real credentials are needed."""
    from action_agent.config import Settings, validate_real_mcp_keys

    settings = Settings(
        use_stub_mcp=False,
        notion_api_key="fake-notion-key",
        notion_database_id="fake-db-id",
        jira_url="https://fake.atlassian.net",
        jira_email="fake@example.com",
        jira_api_token="fake-jira-token",
        jira_project_key="FAKE",
        slack_bot_token="xoxb-fake-slack-token",
    )

    # Should not raise anything
    validate_real_mcp_keys(settings)


# ---------------------------------------------------------------------------
# Spec 6
# ---------------------------------------------------------------------------

def test_validate_real_mcp_keys_error_lists_only_missing_keys(monkeypatch):
    """Spec 6: validate_real_mcp_keys raises ValueError that lists ONLY the
    keys that are missing. If only NOTION_API_KEY is absent, only that key
    name should appear in the error message."""
    from action_agent.config import Settings, validate_real_mcp_keys

    # All keys present except notion_api_key
    settings = Settings(
        use_stub_mcp=False,
        notion_api_key="",          # intentionally blank
        notion_database_id="fake-db-id",
        jira_url="https://fake.atlassian.net",
        jira_email="fake@example.com",
        jira_api_token="fake-jira-token",
        jira_project_key="FAKE",
        slack_bot_token="xoxb-fake-slack-token",
    )

    with pytest.raises(ValueError) as exc_info:
        validate_real_mcp_keys(settings)

    error_text = str(exc_info.value)
    assert "NOTION_API_KEY" in error_text, (
        "NOTION_API_KEY should appear in the error since it is blank"
    )
    # Keys that ARE present must NOT appear in the error
    for present_key in (
        "NOTION_DATABASE_ID",
        "JIRA_URL",
        "JIRA_EMAIL",
        "JIRA_API_TOKEN",
        "JIRA_PROJECT_KEY",
        "SLACK_BOT_TOKEN",
    ):
        assert present_key not in error_text, (
            f"'{present_key}' should NOT appear in error (it has a value), "
            f"got: {error_text!r}"
        )


# ---------------------------------------------------------------------------
# Spec 7
# ---------------------------------------------------------------------------

def test_real_connections_use_npx_command():
    """Spec 7: When use_stub_mcp=False, the connections returned by
    get_active_connections use 'npx' as the command, not sys.executable."""
    import sys
    from action_agent.mcp.config import get_active_connections
    from action_agent.config import Settings

    settings = Settings(
        use_stub_mcp=False,
        notion_api_key="fake-notion-key",
        notion_database_id="fake-db-id",
        jira_url="https://fake.atlassian.net",
        jira_email="fake@example.com",
        jira_api_token="fake-jira-token",
        jira_project_key="FAKE",
        slack_bot_token="xoxb-fake-slack-token",
    )
    result = get_active_connections(settings)

    for server_name in ("notion", "jira", "slack"):
        cmd = result[server_name].get("command")
        assert cmd == "npx", (
            f"Expected command 'npx' for server '{server_name}', got '{cmd}'"
        )
        assert cmd != sys.executable, (
            f"Real connections must NOT use sys.executable for server '{server_name}'"
        )


# ---------------------------------------------------------------------------
# Spec 8  (integration — auto-skip when NOTION_API_KEY is blank)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("NOTION_API_KEY"),
    reason="NOTION_API_KEY not set — skipping live Notion integration test",
)
async def test_notion_create_page_real_returns_notion_url():
    """Spec 8 (integration): With real Notion credentials, notion_create_page
    creates a page and the returned URL contains 'notion.so'. Skipped when
    NOTION_API_KEY is blank."""
    from action_agent.mcp.config import get_active_connections
    from action_agent.config import Settings
    from langchain_mcp_adapters.client import MultiServerMCPClient

    settings = Settings(use_stub_mcp=False)
    connections = get_active_connections(settings)

    client = MultiServerMCPClient({"notion": connections["notion"]})
    tools = await client.get_tools(server_name="notion")
    create = next(t for t in tools if t.name == "notion_create_page")

    raw = await create.ainvoke({
        "title": "Phase 4 integration test page",
        "description": "Automated test — safe to delete",
        "owner": "Test Agent",
        "deadline": "2026-12-31",
        "priority": "low",
    })
    data = json.loads(raw) if isinstance(raw, str) else raw
    url = data.get("url", "")
    assert "notion.so" in url, (
        f"Expected URL to contain 'notion.so', got: {url!r}"
    )


# ---------------------------------------------------------------------------
# Spec 9  (integration — auto-skip when JIRA_URL is blank)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("JIRA_URL"),
    reason="JIRA_URL not set — skipping live Jira integration test",
)
async def test_jira_create_issue_real_returns_correct_key_prefix():
    """Spec 9 (integration): With real Jira credentials, jira_create_issue
    creates an issue and the returned key starts with settings.jira_project_key.
    Skipped when JIRA_URL is blank."""
    from action_agent.mcp.config import get_active_connections
    from action_agent.config import Settings
    from langchain_mcp_adapters.client import MultiServerMCPClient

    settings = Settings(use_stub_mcp=False)
    connections = get_active_connections(settings)

    client = MultiServerMCPClient({"jira": connections["jira"]})
    tools = await client.get_tools(server_name="jira")
    create = next(t for t in tools if t.name == "jira_create_issue")

    raw = await create.ainvoke({
        "summary": "Phase 4 integration test issue",
        "description": "Automated test — safe to delete",
        "assignee": "test-user",
        "due_date": "2026-12-31",
    })
    data = json.loads(raw) if isinstance(raw, str) else raw
    issue_key = data.get("key", "")
    assert issue_key.startswith(settings.jira_project_key), (
        f"Expected issue key to start with '{settings.jira_project_key}', "
        f"got: {issue_key!r}"
    )


# ---------------------------------------------------------------------------
# Spec 10  (integration — auto-skip when SLACK_BOT_TOKEN is blank)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("SLACK_BOT_TOKEN"),
    reason="SLACK_BOT_TOKEN not set — skipping live Slack integration test",
)
async def test_slack_post_message_real_returns_ok():
    """Spec 10 (integration): With real Slack credentials, slack_post_message
    returns ok=True. Skipped when SLACK_BOT_TOKEN is blank."""
    from action_agent.mcp.config import get_active_connections
    from action_agent.config import Settings
    from langchain_mcp_adapters.client import MultiServerMCPClient

    settings = Settings(use_stub_mcp=False)
    connections = get_active_connections(settings)

    client = MultiServerMCPClient({"slack": connections["slack"]})
    tools = await client.get_tools(server_name="slack")
    post = next(t for t in tools if t.name == "slack_post_message")

    raw = await post.ainvoke({
        "channel": settings.slack_channel,
        "text": "Phase 4 integration test message — safe to ignore",
    })
    data = json.loads(raw) if isinstance(raw, str) else raw
    assert data.get("ok") is True, (
        f"Expected ok=True from Slack, got: {data!r}"
    )


# ---------------------------------------------------------------------------
# Spec 11  (regression)
# ---------------------------------------------------------------------------

async def test_stub_mode_returns_stub_connections_with_all_tool_names():
    """Spec 11 (regression): In stub mode (USE_STUB_MCP=true),
    get_active_connections(settings) still returns STUB_CONNECTIONS and all
    stub MCP tool names are present (notion_create_page, jira_create_issue,
    slack_post_message)."""
    from action_agent.mcp.config import get_active_connections, STUB_CONNECTIONS
    from action_agent.config import Settings
    from langchain_mcp_adapters.client import MultiServerMCPClient

    settings = Settings(use_stub_mcp=True)
    connections = get_active_connections(settings)

    # Structural regression: still equal to STUB_CONNECTIONS
    assert connections == STUB_CONNECTIONS, (
        "In stub mode, get_active_connections must return STUB_CONNECTIONS"
    )

    # Functional regression: all three expected tool names are reachable
    client = MultiServerMCPClient(connections)
    all_tool_names: set[str] = set()
    for server_name in connections:
        tools = await client.get_tools(server_name=server_name)
        all_tool_names.update(t.name for t in tools)

    for expected_tool in ("notion_create_page", "jira_create_issue", "slack_post_message"):
        assert expected_tool in all_tool_names, (
            f"Stub mode must expose tool '{expected_tool}', "
            f"found tools: {all_tool_names}"
        )
