"""
Phase 3 tests — stub MCP dispatch with parallel fan-out.
Tests the full graph with real MCP tool calls against stub servers.
"""
import json
from pathlib import Path

TRANSCRIPT = (Path(__file__).parent / "fixtures" / "sample_transcript.txt").read_text()
TEAM = ["Alice Smith", "Bob Jones", "Carol White", "David Lee"]


# ── MCP tool loading ──────────────────────────────────────────────────────────

async def test_mcp_tools_load_all_servers():
    """get_mcp_tools() context manager yields tools for notion, jira, slack."""
    from action_agent.mcp.client import get_mcp_tools
    async with get_mcp_tools() as tools:
        assert "notion" in tools
        assert "jira" in tools
        assert "slack" in tools
        assert len(tools["notion"]) > 0
        assert len(tools["jira"]) > 0
        assert len(tools["slack"]) > 0


async def test_notion_stub_has_expected_tools():
    from action_agent.mcp.client import get_mcp_tools
    async with get_mcp_tools() as tools:
        names = {t.name for t in tools["notion"]}
        assert "notion_create_page" in names


async def test_jira_stub_has_expected_tools():
    from action_agent.mcp.client import get_mcp_tools
    async with get_mcp_tools() as tools:
        names = {t.name for t in tools["jira"]}
        assert "jira_create_issue" in names


async def test_slack_stub_has_expected_tools():
    from action_agent.mcp.client import get_mcp_tools
    async with get_mcp_tools() as tools:
        names = {t.name for t in tools["slack"]}
        assert "slack_post_message" in names


# ── Direct stub tool calls ────────────────────────────────────────────────────

async def test_notion_stub_create_page_returns_id():
    from action_agent.mcp.client import get_mcp_tools
    async with get_mcp_tools() as tools:
        create = next(t for t in tools["notion"] if t.name == "notion_create_page")
        raw = await create.ainvoke({
            "title": "Write unit tests",
            "description": "Cover the new dispatch pipeline",
            "owner": "Alice Smith",
            "deadline": "2026-05-10",
            "priority": "high",
        })
        data = json.loads(raw) if isinstance(raw, str) else raw
        assert "id" in data
        assert "url" in data
        assert data.get("status") == "created"


async def test_jira_stub_create_issue_returns_key():
    from action_agent.mcp.client import get_mcp_tools
    async with get_mcp_tools() as tools:
        create = next(t for t in tools["jira"] if t.name == "jira_create_issue")
        raw = await create.ainvoke({
            "summary": "Fix authentication bug",
            "description": "OAuth2 token validation failing",
            "assignee": "Bob Jones",
            "due_date": "2026-05-15",
        })
        data = json.loads(raw) if isinstance(raw, str) else raw
        assert "key" in data
        assert data["key"].startswith("PROJ-")
        assert data.get("status") == "created"


async def test_slack_stub_post_message_returns_ok():
    from action_agent.mcp.client import get_mcp_tools
    async with get_mcp_tools() as tools:
        post = next(t for t in tools["slack"] if t.name == "slack_post_message")
        raw = await post.ainvoke({
            "channel": "#meeting-debriefs",
            "text": "Test message from debrief agent",
        })
        data = json.loads(raw) if isinstance(raw, str) else raw
        assert data.get("ok") is True
        assert "ts" in data


# ── Full graph with MCP dispatch ──────────────────────────────────────────────

async def _run_full_graph():
    """Helper: run full graph with MCP tools loaded, return final state."""
    from action_agent.graph.builder import build_graph
    from action_agent.mcp.client import get_mcp_tools

    graph = build_graph()
    initial_state = {
        "transcript": TRANSCRIPT,
        "team_members": TEAM,
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

    async with get_mcp_tools() as mcp_tools:
        config = {"configurable": {"thread_id": "phase3-test", "mcp_tools": mcp_tools}}
        final_updates: dict = {}
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            for updates in event.values():
                if isinstance(updates, dict):
                    final_updates.update(updates)

    return {**initial_state, **final_updates}


async def test_full_graph_status_complete():
    state = await _run_full_graph()
    assert state["status"] == "complete", f"Expected 'complete', got: {state['status']}"


async def test_dispatch_results_all_three_tools_present():
    state = await _run_full_graph()
    tool_names = {r.tool for r in state["dispatch_results"]}
    assert "notion" in tool_names, "Missing notion dispatch result"
    assert "jira" in tool_names, "Missing jira dispatch result"
    assert "slack" in tool_names, "Missing slack dispatch result"


async def test_dispatch_results_all_successful():
    state = await _run_full_graph()
    failures = [r for r in state["dispatch_results"] if not r.success]
    assert len(failures) == 0, f"Failed dispatches: {failures}"


async def test_dispatch_notion_results_have_ids():
    state = await _run_full_graph()
    notion_results = [r for r in state["dispatch_results"] if r.tool == "notion"]
    assert len(notion_results) > 0
    assert all(r.item_id for r in notion_results)


async def test_dispatch_jira_results_have_keys():
    state = await _run_full_graph()
    jira_results = [r for r in state["dispatch_results"] if r.tool == "jira"]
    assert len(jira_results) > 0
    assert all(r.item_id for r in jira_results)


async def test_valid_items_were_dispatched():
    state = await _run_full_graph()
    vr = state.get("validation_result")
    assert vr is not None
    assert len(vr.valid_items) > 0, "Expected at least some fully-resolved action items"


async def test_summary_populated():
    state = await _run_full_graph()
    assert state.get("summary") is not None
    assert state["summary"].title


# ── Phase 1 + 2 regression ────────────────────────────────────────────────────

def test_validation_agent_regression():
    from action_agent.agents.validator import ValidationAgent
    from action_agent.models.schemas import ActionItem
    agent = ValidationAgent()
    items = [
        ActionItem(id="ai-001", description="Merge PR", owner="Alice", deadline="2026-05-10"),
        ActionItem(id="ai-002", description="No owner"),
    ]
    result = agent.run(items=items, attempt=1)
    assert len(result.valid_items) == 1
    assert len(result.flagged_items) == 1
