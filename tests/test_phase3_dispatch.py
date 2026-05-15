"""
Phase 3 tests — local dispatch node (writes to SQLite, no external services).
"""
import tempfile
import os
from pathlib import Path

TRANSCRIPT = (Path(__file__).parent / "fixtures" / "sample_transcript.txt").read_text()
TEAM = ["Alice Smith", "Bob Jones", "Carol White", "David Lee"]


def _make_state(items=None):
    from action_agent.models.schemas import ActionItem, ValidationResult, MeetingSummary
    if items is None:
        items = [
            ActionItem(id="ai-001", description="Write docs", owner="Alice Smith", deadline="2026-06-01"),
            ActionItem(id="ai-002", description="Fix bug", owner="Bob Jones", deadline="2026-06-15"),
        ]
    return {
        "validation_result": ValidationResult(valid_items=items, flagged_items=[], is_complete=True),
        "summary": MeetingSummary(
            title="Test Meeting",
            participants=["Alice Smith", "Bob Jones"],
            key_decisions=[],
            summary="Test summary.",
        ),
        "dispatch_results": [],
    }


# ── dispatch_local_node unit tests ────────────────────────────────────────────

async def test_dispatch_local_returns_success():
    """dispatch_local_node always returns success (no external dependencies)."""
    from action_agent.graph.nodes import dispatch_local_node

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        result = await dispatch_local_node(state, {"configurable": {"thread_id": "t-001"}}, db_path=db_path)
        assert len(result["dispatch_results"]) == 1
        assert result["dispatch_results"][0].success is True
        assert result["dispatch_results"][0].tool == "local"
    finally:
        os.unlink(db_path)


async def test_dispatch_local_item_id_is_meeting_id():
    """The dispatch result item_id is the meeting's uuid from the DB."""
    from action_agent.graph.nodes import dispatch_local_node
    from action_agent.db import get_meetings

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        result = await dispatch_local_node(state, {"configurable": {"thread_id": "t-002"}}, db_path=db_path)
        meetings = await get_meetings(db_path)
        assert result["dispatch_results"][0].item_id == meetings[0]["id"]
    finally:
        os.unlink(db_path)


async def test_dispatch_local_persists_two_tasks():
    """dispatch_local_node persists all action items as tasks."""
    from action_agent.graph.nodes import dispatch_local_node
    from action_agent.db import get_tasks

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        await dispatch_local_node(state, {"configurable": {"thread_id": "t-003"}}, db_path=db_path)
        tasks = await get_tasks(db_path)
        assert len(tasks) == 2
    finally:
        os.unlink(db_path)


async def test_dispatch_local_persists_meeting():
    """dispatch_local_node persists the meeting summary."""
    from action_agent.graph.nodes import dispatch_local_node
    from action_agent.db import get_meetings

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        await dispatch_local_node(state, {"configurable": {"thread_id": "t-004"}}, db_path=db_path)
        meetings = await get_meetings(db_path)
        assert len(meetings) == 1
        assert meetings[0]["title"] == "Test Meeting"
    finally:
        os.unlink(db_path)


async def test_dispatch_local_persists_channel_message():
    """dispatch_local_node creates a channel broadcast message."""
    from action_agent.graph.nodes import dispatch_local_node
    from action_agent.db import get_channel

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        await dispatch_local_node(state, {"configurable": {"thread_id": "t-005"}}, db_path=db_path)
        messages = await get_channel(db_path)
        assert len(messages) == 1
    finally:
        os.unlink(db_path)


async def test_dispatch_empty_items_still_succeeds():
    """Dispatch with no action items still creates meeting and channel message."""
    from action_agent.models.schemas import ValidationResult, MeetingSummary
    from action_agent.graph.nodes import dispatch_local_node
    from action_agent.db import get_meetings, get_channel

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = {
            "validation_result": ValidationResult(valid_items=[], flagged_items=[], is_complete=True),
            "summary": MeetingSummary(
                title="Empty Meeting",
                participants=[],
                key_decisions=[],
                summary="No items.",
            ),
            "dispatch_results": [],
        }
        result = await dispatch_local_node(state, {"configurable": {"thread_id": "t-empty"}}, db_path=db_path)
        assert result["dispatch_results"][0].success is True
        meetings = await get_meetings(db_path)
        assert len(meetings) == 1
    finally:
        os.unlink(db_path)


# ── Full graph integration ────────────────────────────────────────────────────

async def _run_full_graph(db_path: str):
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
    config = {"configurable": {"thread_id": f"phase3-test-{db_path[-6:]}"}}

    # Pass db_path via node override not supported directly; patch settings
    import action_agent.graph.nodes as nodes_mod
    original = nodes_mod._DEFAULT_DB
    nodes_mod._DEFAULT_DB = db_path
    try:
        final_updates: dict = {}
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            for updates in event.values():
                if isinstance(updates, dict):
                    final_updates.update(updates)
        return {**initial_state, **final_updates}
    finally:
        nodes_mod._DEFAULT_DB = original


async def test_full_graph_status_complete():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = await _run_full_graph(db_path)
        assert state["status"] == "complete", f"Expected 'complete', got: {state['status']}"
    finally:
        os.unlink(db_path)


async def test_full_graph_dispatch_result_has_local_tool():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = await _run_full_graph(db_path)
        tool_names = {r.tool for r in state["dispatch_results"]}
        assert "local" in tool_names
        assert "notion" not in tool_names
        assert "jira" not in tool_names
        assert "slack" not in tool_names
    finally:
        os.unlink(db_path)


async def test_full_graph_tasks_saved_to_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await _run_full_graph(db_path)
        from action_agent.db import get_tasks
        tasks = await get_tasks(db_path)
        assert len(tasks) > 0
    finally:
        os.unlink(db_path)


async def test_full_graph_meeting_saved_to_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await _run_full_graph(db_path)
        from action_agent.db import get_meetings
        meetings = await get_meetings(db_path)
        assert len(meetings) == 1
    finally:
        os.unlink(db_path)


async def test_full_graph_summary_populated():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = await _run_full_graph(db_path)
        assert state.get("summary") is not None
        assert state["summary"].title
    finally:
        os.unlink(db_path)


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
