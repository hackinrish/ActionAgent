"""
Phase 3 tests — dispatch nodes with direct SDK calls (dry-run when no credentials set).
"""
from pathlib import Path

TRANSCRIPT = (Path(__file__).parent / "fixtures" / "sample_transcript.txt").read_text()
TEAM = ["Alice Smith", "Bob Jones", "Carol White", "David Lee"]


def _make_state(items=None):
    from action_agent.models.schemas import ActionItem, ValidationResult
    if items is None:
        items = [
            ActionItem(id="ai-001", description="Write docs", owner="Alice Smith", deadline="2026-06-01"),
            ActionItem(id="ai-002", description="Fix bug", owner="Bob Jones", deadline="2026-06-15"),
        ]
    return {
        "validation_result": ValidationResult(valid_items=items, flagged_items=[], is_complete=True),
        "summary": None,
        "dispatch_results": [],
    }


# ── Dispatch unit tests (dry-run mode, no credentials required) ───────────────

async def test_dispatch_notion_dry_run_succeeds():
    """Without credentials, notion dispatch returns successful dry-run results."""
    from action_agent.graph.nodes import dispatch_notion_node
    state = _make_state()
    result = await dispatch_notion_node(state, {"configurable": {}})
    assert len(result["dispatch_results"]) == 2
    assert all(r.success for r in result["dispatch_results"])
    assert all(r.tool == "notion" for r in result["dispatch_results"])


async def test_dispatch_jira_dry_run_succeeds():
    """Without credentials, jira dispatch returns successful dry-run results."""
    from action_agent.graph.nodes import dispatch_jira_node
    state = _make_state()
    result = await dispatch_jira_node(state, {"configurable": {}})
    assert len(result["dispatch_results"]) == 2
    assert all(r.success for r in result["dispatch_results"])
    assert all(r.tool == "jira" for r in result["dispatch_results"])


async def test_dispatch_slack_dry_run_succeeds():
    """Without credentials, slack dispatch returns a successful dry-run result."""
    from action_agent.graph.nodes import dispatch_slack_node
    state = _make_state()
    result = await dispatch_slack_node(state, {"configurable": {}})
    assert result["dispatch_results"][0].success
    assert result["dispatch_results"][0].tool == "slack"


async def test_dispatch_notion_results_have_item_ids():
    from action_agent.graph.nodes import dispatch_notion_node
    state = _make_state()
    result = await dispatch_notion_node(state, {"configurable": {}})
    assert all(r.item_id for r in result["dispatch_results"])


async def test_dispatch_jira_results_have_item_ids():
    from action_agent.graph.nodes import dispatch_jira_node
    state = _make_state()
    result = await dispatch_jira_node(state, {"configurable": {}})
    assert all(r.item_id for r in result["dispatch_results"])


async def test_dispatch_empty_items_returns_fallback():
    """Dispatch nodes with no action items return a single fallback result."""
    from action_agent.models.schemas import ValidationResult
    from action_agent.graph.nodes import dispatch_notion_node
    state = {"validation_result": ValidationResult(valid_items=[], flagged_items=[], is_complete=True)}
    result = await dispatch_notion_node(state, {"configurable": {}})
    assert len(result["dispatch_results"]) == 1
    assert result["dispatch_results"][0].success


# ── Full graph integration ────────────────────────────────────────────────────

async def _run_full_graph():
    from action_agent.graph.builder import build_graph
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
    config = {"configurable": {"thread_id": "phase3-test"}}
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
    assert "notion" in tool_names
    assert "jira" in tool_names
    assert "slack" in tool_names


async def test_dispatch_results_all_successful():
    state = await _run_full_graph()
    failures = [r for r in state["dispatch_results"] if not r.success]
    assert len(failures) == 0, f"Failed dispatches: {failures}"


async def test_dispatch_notion_results_have_ids():
    state = await _run_full_graph()
    notion = [r for r in state["dispatch_results"] if r.tool == "notion"]
    assert len(notion) > 0
    assert all(r.item_id for r in notion)


async def test_dispatch_jira_results_have_keys():
    state = await _run_full_graph()
    jira = [r for r in state["dispatch_results"] if r.tool == "jira"]
    assert len(jira) > 0
    assert all(r.item_id for r in jira)


async def test_valid_items_were_dispatched():
    state = await _run_full_graph()
    vr = state.get("validation_result")
    assert vr is not None
    assert len(vr.valid_items) > 0


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
