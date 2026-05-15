"""
Phase 6 tests — Live integration & hardening.

Covers:
  1. Integration tests (Notion / Jira / Slack) — auto-skip when credentials absent
  2. Retry with exponential backoff on dispatch SDK errors
  3. Structured JSON logging (action_agent/utils/logging.py)
  4. Persistent run history via SqliteSaver checkpointer
  5. GET /runs/{thread_id} API endpoint
"""
from __future__ import annotations

import io
import json
import logging
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
import pytest


# ─── Shared fixtures / helpers ────────────────────────────────────────────────

def _make_two_items():
    from action_agent.models.schemas import ActionItem, ValidationResult
    items = [
        ActionItem(id="ai-001", description="Write docs", owner="Alice Smith", deadline="2026-06-01"),
        ActionItem(id="ai-002", description="Fix bug", owner="Bob Jones", deadline="2026-06-15"),
    ]
    return ValidationResult(valid_items=items, flagged_items=[], is_complete=True)


def _make_state(vr=None):
    return {
        "validation_result": vr or _make_two_items(),
        "summary": None,
        "dispatch_results": [],
    }


def _api_client():
    from api import app
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Integration Tests (auto-skip when credentials are absent)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    not os.environ.get("NOTION_API_KEY") or not os.environ.get("NOTION_DATABASE_ID"),
    reason="NOTION_API_KEY / NOTION_DATABASE_ID not set — skipping live Notion test",
)
async def test_integration_notion_live_dispatch_succeeds():
    """With real credentials, notion dispatch creates pages and returns real IDs."""
    from action_agent.graph.nodes import dispatch_notion_node
    state = _make_state()
    result = await dispatch_notion_node(state, {"configurable": {}})
    assert len(result["dispatch_results"]) == 2
    for r in result["dispatch_results"]:
        assert r.success, f"Notion dispatch failed: {r.error_message}"
        assert r.tool == "notion"
        # Real Notion page IDs are UUIDs (contain hyphens), not "dry-run-*"
        assert r.item_id is not None
        assert not r.item_id.startswith("dry-run"), f"Got dry-run ID with live credentials: {r.item_id}"


@pytest.mark.skipif(
    not os.environ.get("JIRA_URL") or not os.environ.get("JIRA_API_TOKEN"),
    reason="JIRA_URL / JIRA_API_TOKEN not set — skipping live Jira test",
)
async def test_integration_jira_live_dispatch_succeeds():
    """With real credentials, jira dispatch creates issues and returns issue keys."""
    from action_agent.graph.nodes import dispatch_jira_node
    state = _make_state()
    result = await dispatch_jira_node(state, {"configurable": {}})
    assert len(result["dispatch_results"]) == 2
    for r in result["dispatch_results"]:
        assert r.success, f"Jira dispatch failed: {r.error_message}"
        assert r.tool == "jira"
        # Real Jira keys look like "PROJ-123", not "DRY-*"
        assert r.item_id is not None
        assert not r.item_id.startswith("DRY-"), f"Got dry-run ID with live credentials: {r.item_id}"


@pytest.mark.skipif(
    not os.environ.get("SLACK_BOT_TOKEN"),
    reason="SLACK_BOT_TOKEN not set — skipping live Slack test",
)
async def test_integration_slack_live_dispatch_succeeds():
    """With real credentials, slack dispatch posts a message and returns a timestamp."""
    from action_agent.graph.nodes import dispatch_slack_node
    state = _make_state()
    result = await dispatch_slack_node(state, {"configurable": {}})
    assert len(result["dispatch_results"]) == 1
    r = result["dispatch_results"][0]
    assert r.success, f"Slack dispatch failed: {r.error_message}"
    assert r.tool == "slack"
    assert r.item_id is not None
    assert r.item_id != "dry-run-slack", f"Got dry-run ID with live credentials: {r.item_id}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Retry with Exponential Backoff
# ═══════════════════════════════════════════════════════════════════════════════

async def test_notion_retry_succeeds_on_second_attempt():
    """Notion dispatch retries after a single transient error and returns success."""
    from action_agent.graph.nodes import dispatch_notion_node

    fake_page = {"id": "notion-page-abc123"}
    mock_pages = AsyncMock()
    # First call raises, second call succeeds
    mock_pages.create.side_effect = [Exception("transient network error"), fake_page]

    with patch.dict(os.environ, {"NOTION_API_KEY": "test-key", "NOTION_DATABASE_ID": "test-db"}):
        with patch("action_agent.graph.nodes.AsyncClient") as MockClient:
            MockClient.return_value.pages = mock_pages
            # Re-import settings so the patch takes effect
            with patch("action_agent.config.settings") as mock_settings:
                mock_settings.notion_api_key = "test-key"
                mock_settings.notion_database_id = "test-db"
                mock_settings.jira_url = ""
                mock_settings.jira_api_token = ""
                mock_settings.slack_bot_token = ""
                state = _make_state()
                result = await dispatch_notion_node(state, {"configurable": {}})

    # At least one result must be successful (the retry succeeded)
    successes = [r for r in result["dispatch_results"] if r.success]
    assert len(successes) >= 1, "Expected at least one success after retry"


async def test_notion_fails_after_max_retries():
    """After max retries (3 attempts), notion dispatch returns DispatchResult(success=False)."""
    from action_agent.graph.nodes import dispatch_notion_node

    mock_pages = AsyncMock()
    mock_pages.create.side_effect = Exception("persistent server error")

    with patch("action_agent.config.settings") as mock_settings:
        mock_settings.notion_api_key = "test-key"
        mock_settings.notion_database_id = "test-db"
        mock_settings.jira_url = ""
        mock_settings.jira_api_token = ""
        mock_settings.slack_bot_token = ""

        with patch("action_agent.graph.nodes.AsyncClient") as MockClient:
            MockClient.return_value.pages = mock_pages

            state = _make_state()
            result = await dispatch_notion_node(state, {"configurable": {}})

    failures = [r for r in result["dispatch_results"] if not r.success]
    assert len(failures) >= 1, "Expected at least one failure after max retries exhausted"
    assert failures[0].error_message is not None
    assert "persistent server error" in failures[0].error_message


async def test_jira_retry_succeeds_on_second_attempt():
    """Jira dispatch retries after a single transient error and returns success."""
    from action_agent.graph.nodes import dispatch_jira_node

    fake_issue = MagicMock()
    fake_issue.key = "PROJ-42"

    with patch("action_agent.config.settings") as mock_settings:
        mock_settings.jira_url = "https://fake.atlassian.net"
        mock_settings.jira_api_token = "fake-token"
        mock_settings.jira_email = "fake@test.com"
        mock_settings.jira_project_key = "PROJ"
        mock_settings.notion_api_key = ""
        mock_settings.notion_database_id = ""
        mock_settings.slack_bot_token = ""

        with patch("action_agent.graph.nodes.JIRA") as MockJIRA:
            mock_jira_client = MagicMock()
            # First call raises, second succeeds
            mock_jira_client.create_issue.side_effect = [
                Exception("transient timeout"),
                fake_issue,
            ]
            MockJIRA.return_value = mock_jira_client

            with patch("asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
                state = _make_state()
                result = await dispatch_jira_node(state, {"configurable": {}})

    successes = [r for r in result["dispatch_results"] if r.success]
    assert len(successes) >= 1, "Expected at least one success after Jira retry"


async def test_jira_fails_after_max_retries():
    """After max retries, jira dispatch returns DispatchResult(success=False)."""
    from action_agent.graph.nodes import dispatch_jira_node

    with patch("action_agent.config.settings") as mock_settings:
        mock_settings.jira_url = "https://fake.atlassian.net"
        mock_settings.jira_api_token = "fake-token"
        mock_settings.jira_email = "fake@test.com"
        mock_settings.jira_project_key = "PROJ"
        mock_settings.notion_api_key = ""
        mock_settings.notion_database_id = ""
        mock_settings.slack_bot_token = ""

        with patch("action_agent.graph.nodes.JIRA") as MockJIRA:
            mock_jira_client = MagicMock()
            mock_jira_client.create_issue.side_effect = Exception("persistent jira error")
            MockJIRA.return_value = mock_jira_client

            with patch("asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
                state = _make_state()
                result = await dispatch_jira_node(state, {"configurable": {}})

    failures = [r for r in result["dispatch_results"] if not r.success]
    assert len(failures) >= 1, "Expected failures after Jira max retries exhausted"
    assert failures[0].error_message is not None


async def test_slack_retry_succeeds_on_second_attempt():
    """Slack dispatch retries after a single transient error and returns success."""
    from action_agent.graph.nodes import dispatch_slack_node

    fake_resp = MagicMock()
    fake_resp.__getitem__ = lambda self, key: True if key == "ok" else "1234567890.123456"
    fake_resp.get = lambda key, default=None: "1234567890.123456" if key == "ts" else default

    mock_client = AsyncMock()
    # First call raises, second succeeds
    mock_client.chat_postMessage.side_effect = [
        Exception("transient slack error"),
        fake_resp,
    ]

    with patch("action_agent.config.settings") as mock_settings:
        mock_settings.slack_bot_token = "xoxb-test-token"
        mock_settings.slack_channel = "#test-channel"
        mock_settings.notion_api_key = ""
        mock_settings.notion_database_id = ""
        mock_settings.jira_url = ""
        mock_settings.jira_api_token = ""

        with patch("action_agent.graph.nodes.AsyncWebClient", return_value=mock_client):
            state = _make_state()
            result = await dispatch_slack_node(state, {"configurable": {}})

    successes = [r for r in result["dispatch_results"] if r.success]
    assert len(successes) >= 1, "Expected success after Slack retry"


async def test_slack_fails_after_max_retries():
    """After max retries, slack dispatch returns DispatchResult(success=False)."""
    from action_agent.graph.nodes import dispatch_slack_node

    mock_client = AsyncMock()
    mock_client.chat_postMessage.side_effect = Exception("slack API down")

    with patch("action_agent.config.settings") as mock_settings:
        mock_settings.slack_bot_token = "xoxb-test-token"
        mock_settings.slack_channel = "#test-channel"
        mock_settings.notion_api_key = ""
        mock_settings.notion_database_id = ""
        mock_settings.jira_url = ""
        mock_settings.jira_api_token = ""

        with patch("action_agent.graph.nodes.AsyncWebClient", return_value=mock_client):
            state = _make_state()
            result = await dispatch_slack_node(state, {"configurable": {}})

    r = result["dispatch_results"][0]
    assert r.success is False, "Expected failure after Slack max retries exhausted"
    assert r.error_message is not None
    assert "slack API down" in r.error_message


async def test_retry_is_attempted_multiple_times():
    """Verify that the dispatch node actually retries (not just a single attempt)."""
    from action_agent.graph.nodes import dispatch_notion_node

    mock_pages = AsyncMock()
    # Fail twice, succeed on third
    fake_page = {"id": "page-after-two-failures"}
    mock_pages.create.side_effect = [
        Exception("error 1"),
        Exception("error 2"),
        fake_page,
    ]

    with patch("action_agent.config.settings") as mock_settings:
        mock_settings.notion_api_key = "test-key"
        mock_settings.notion_database_id = "test-db"
        mock_settings.jira_url = ""
        mock_settings.jira_api_token = ""
        mock_settings.slack_bot_token = ""

        with patch("action_agent.graph.nodes.AsyncClient") as MockClient:
            MockClient.return_value.pages = mock_pages
            state = _make_state()
            # Only one item so create is called once per attempt
            from action_agent.models.schemas import ActionItem, ValidationResult
            single_item_state = {
                "validation_result": ValidationResult(
                    valid_items=[ActionItem(id="ai-001", description="Task", owner="Alice", deadline="2026-06-01")],
                    flagged_items=[],
                    is_complete=True,
                ),
                "summary": None,
                "dispatch_results": [],
            }
            result = await dispatch_notion_node(single_item_state, {"configurable": {}})

    # create should have been called at least 3 times (2 failures + 1 success)
    assert mock_pages.create.call_count >= 3, (
        f"Expected at least 3 attempts (2 failures + 1 success), got {mock_pages.create.call_count}"
    )
    successes = [r for r in result["dispatch_results"] if r.success]
    assert len(successes) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Structured JSON Logging
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_logger_returns_logger():
    """get_logger(name) returns a standard logging.Logger instance."""
    from action_agent.utils.logging import get_logger
    logger = get_logger("test.phase6")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test.phase6"


def test_get_logger_same_name_returns_same_logger():
    """Calling get_logger with the same name returns the same logger instance."""
    from action_agent.utils.logging import get_logger
    logger1 = get_logger("test.singleton")
    logger2 = get_logger("test.singleton")
    assert logger1 is logger2


def test_log_output_is_valid_json():
    """Each log line emitted by the structured logger is valid JSON."""
    from action_agent.utils.logging import get_logger

    stream = io.StringIO()
    logger = get_logger("test.json_output")

    # Replace handlers with one that writes to our stream
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    logger.info("hello structured world")

    output = stream.getvalue().strip()
    assert output, "Logger produced no output"

    # Each line should parse as JSON
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)  # Raises ValueError if not valid JSON
        assert isinstance(parsed, dict)


def test_log_line_contains_required_fields():
    """Each JSON log line contains level, timestamp, message, and logger fields."""
    from action_agent.utils.logging import get_logger

    stream = io.StringIO()
    logger = get_logger("test.fields")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    logger.warning("checking fields")

    output = stream.getvalue().strip()
    assert output, "Logger produced no output"

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        assert "level" in parsed, f"Missing 'level' field: {parsed}"
        assert "timestamp" in parsed, f"Missing 'timestamp' field: {parsed}"
        assert "message" in parsed, f"Missing 'message' field: {parsed}"
        assert "logger" in parsed, f"Missing 'logger' field: {parsed}"


def test_log_level_field_reflects_actual_level():
    """The level field in JSON output matches the actual log level used."""
    from action_agent.utils.logging import get_logger

    stream = io.StringIO()
    logger = get_logger("test.level_field")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    logger.warning("this is a warning")

    output = stream.getvalue().strip()
    parsed = json.loads(output.splitlines()[-1])
    assert parsed["level"].upper() in ("WARNING", "WARN")


def test_log_node_event_emits_node_field():
    """log_node_event emits a JSON line that includes a 'node' field."""
    from action_agent.utils.logging import get_logger, log_node_event

    stream = io.StringIO()
    logger = get_logger("test.node_event")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    log_node_event(logger, node_name="dispatch_notion", event="started")

    output = stream.getvalue().strip()
    assert output, "log_node_event produced no output"

    parsed = json.loads(output.splitlines()[-1])
    assert "node" in parsed, f"Missing 'node' field in log_node_event output: {parsed}"
    assert parsed["node"] == "dispatch_notion"


def test_log_node_event_includes_base_fields():
    """log_node_event output still contains all required base fields."""
    from action_agent.utils.logging import get_logger, log_node_event

    stream = io.StringIO()
    logger = get_logger("test.node_event_fields")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    log_node_event(logger, node_name="dispatch_slack", event="complete")

    output = stream.getvalue().strip()
    parsed = json.loads(output.splitlines()[-1])
    for field in ("level", "timestamp", "message", "logger", "node"):
        assert field in parsed, f"Missing '{field}' field: {parsed}"


def test_log_message_field_contains_event():
    """The message field in log_node_event output includes the event string."""
    from action_agent.utils.logging import get_logger, log_node_event

    stream = io.StringIO()
    logger = get_logger("test.node_event_message")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)

    log_node_event(logger, node_name="dispatch_jira", event="retry_attempt")

    output = stream.getvalue().strip()
    parsed = json.loads(output.splitlines()[-1])
    assert "retry_attempt" in parsed["message"] or "retry_attempt" in str(parsed)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Persistent Run History (SqliteSaver checkpointer)
# ═══════════════════════════════════════════════════════════════════════════════

async def test_sqlite_saver_import():
    """AsyncSqliteSaver can be imported from langgraph.checkpoint.sqlite.aio."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: F401
    assert AsyncSqliteSaver is not None


async def test_checkpoint_saved_after_graph_run():
    """After invoking the graph with AsyncSqliteSaver, the checkpoint can be retrieved."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from action_agent.graph.builder import build_graph

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        thread_id = "phase6-history-test-001"
        config = {"configurable": {"thread_id": thread_id}}

        initial_state = {
            "transcript": "Alice: Fix the login bug by Friday. Bob: Sure.",
            "team_members": ["Alice", "Bob"],
            "messages": [],
            "summary": None,
            "raw_action_items": [],
            "assigned_action_items": [],
            "validation_result": None,
            "validation_attempts": 0,
            "dispatch_results": [],
            "error": None,
            "status": "running",
        }

        await graph.ainvoke(initial_state, config)

        checkpoint = await checkpointer.aget(config)
        assert checkpoint is not None, "No checkpoint found after graph.ainvoke"


async def test_checkpoint_contains_final_state():
    """The saved checkpoint contains the final pipeline state (status, dispatch_results)."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from action_agent.graph.builder import build_graph

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        thread_id = "phase6-history-test-002"
        config = {"configurable": {"thread_id": thread_id}}

        initial_state = {
            "transcript": "Carol: We need to update the docs by next Monday.",
            "team_members": ["Carol"],
            "messages": [],
            "summary": None,
            "raw_action_items": [],
            "assigned_action_items": [],
            "validation_result": None,
            "validation_attempts": 0,
            "dispatch_results": [],
            "error": None,
            "status": "running",
        }

        await graph.ainvoke(initial_state, config)

        checkpoint = await checkpointer.aget(config)
        assert checkpoint is not None

        channel_values = checkpoint.get("channel_values", {})
        assert "status" in channel_values, f"checkpoint missing 'status': {list(channel_values.keys())}"
        assert channel_values["status"] in ("complete", "error")


async def test_checkpoint_is_retrievable_by_thread_id():
    """Checkpoints are isolated per thread_id — different threads have independent history."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from action_agent.graph.builder import build_graph

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)

        base_state = {
            "transcript": "Dave: Deploy the service by Thursday.",
            "team_members": ["Dave"],
            "messages": [],
            "summary": None,
            "raw_action_items": [],
            "assigned_action_items": [],
            "validation_result": None,
            "validation_attempts": 0,
            "dispatch_results": [],
            "error": None,
            "status": "running",
        }

        thread_a = "phase6-thread-A"
        thread_b = "phase6-thread-B"

        await graph.ainvoke(base_state, {"configurable": {"thread_id": thread_a}})

        cp_a = await checkpointer.aget({"configurable": {"thread_id": thread_a}})
        assert cp_a is not None, "Checkpoint for thread A should exist"

        cp_b = await checkpointer.aget({"configurable": {"thread_id": thread_b}})
        assert cp_b is None, "Checkpoint for thread B should not exist before it runs"


async def test_build_graph_accepts_sqlite_checkpointer():
    """build_graph() accepts an AsyncSqliteSaver instance without raising errors."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from action_agent.graph.builder import build_graph

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        assert graph is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. GET /runs/{thread_id} API Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

async def test_runs_endpoint_returns_404_for_unknown_thread():
    """GET /runs/{thread_id} returns 404 when the thread_id has no run history."""
    async with _api_client() as client:
        resp = await client.get("/runs/nonexistent-thread-xyz-999")
    assert resp.status_code == 404


async def test_runs_endpoint_returns_200_for_known_thread():
    """GET /runs/{thread_id} returns 200 for a thread_id that ran successfully."""
    thread_id = "phase6-api-run-test-001"

    # First run a debrief so a thread_id exists in the persistent checkpointer
    async with _api_client() as client:
        resp = await client.post(
            "/debrief",
            json={
                "transcript": "Eve: Please review the design doc by Wednesday.",
                "team_members": ["Eve"],
                "thread_id": thread_id,
            },
            timeout=120,
        )
        assert resp.status_code == 200

    # Now retrieve run history for that thread
    async with _api_client() as client:
        resp = await client.get(f"/runs/{thread_id}")
    assert resp.status_code == 200


async def test_runs_endpoint_response_has_required_fields():
    """GET /runs/{thread_id} response contains status, action_items, and summary."""
    thread_id = "phase6-api-run-test-002"

    async with _api_client() as client:
        await client.post(
            "/debrief",
            json={
                "transcript": "Frank: Write the release notes by Friday.",
                "team_members": ["Frank"],
                "thread_id": thread_id,
            },
            timeout=120,
        )

    async with _api_client() as client:
        resp = await client.get(f"/runs/{thread_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body, f"Missing 'status' in response: {body}"
    assert "action_items" in body, f"Missing 'action_items' in response: {body}"
    assert "summary" in body, f"Missing 'summary' in response: {body}"


async def test_runs_endpoint_status_is_complete_or_error():
    """GET /runs/{thread_id} status field is either 'complete' or 'error'."""
    thread_id = "phase6-api-run-test-003"

    async with _api_client() as client:
        await client.post(
            "/debrief",
            json={
                "transcript": "Grace: Update dependencies by Monday.",
                "team_members": ["Grace"],
                "thread_id": thread_id,
            },
            timeout=120,
        )

    async with _api_client() as client:
        resp = await client.get(f"/runs/{thread_id}")

    body = resp.json()
    assert body["status"] in ("complete", "error"), f"Unexpected status: {body['status']}"


async def test_runs_endpoint_action_items_is_list():
    """GET /runs/{thread_id} action_items field is a list."""
    thread_id = "phase6-api-run-test-004"

    async with _api_client() as client:
        await client.post(
            "/debrief",
            json={
                "transcript": "Henry: Deploy the new version by Thursday.",
                "team_members": ["Henry"],
                "thread_id": thread_id,
            },
            timeout=120,
        )

    async with _api_client() as client:
        resp = await client.get(f"/runs/{thread_id}")

    body = resp.json()
    assert isinstance(body["action_items"], list)


async def test_runs_endpoint_404_body_has_detail():
    """GET /runs/{thread_id} 404 response contains a 'detail' field."""
    async with _api_client() as client:
        resp = await client.get("/runs/no-such-thread-ever")
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
