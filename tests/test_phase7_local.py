"""
Phase 7 tests — Local-first revamp.

Covers:
  1. action_agent/db.py — SQLite schema, CRUD helpers
  2. dispatch_local_node — writes meeting/tasks/channel to DB
  3. New API endpoints: GET /tasks, PATCH /tasks/{id}, GET /meetings, GET /meetings/{id}, GET /channel
"""
from __future__ import annotations

import tempfile
import os
import json
import httpx
import pytest


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_items():
    from action_agent.models.schemas import ActionItem, ValidationResult
    items = [
        ActionItem(id="ai-001", description="Write docs", owner="Alice Smith", deadline="2026-06-01"),
        ActionItem(id="ai-002", description="Fix bug", owner="Bob Jones", deadline="2026-06-15"),
    ]
    return ValidationResult(valid_items=items, flagged_items=[], is_complete=True)


def _make_summary():
    from action_agent.models.schemas import MeetingSummary
    return MeetingSummary(
        title="Sprint Planning",
        date="2026-05-14",
        participants=["Alice Smith", "Bob Jones"],
        key_decisions=["Ship feature X by May"],
        summary="Team aligned on Q2 roadmap.",
    )


def _make_state(meeting_id="meeting-abc"):
    return {
        "validation_result": _make_items(),
        "summary": _make_summary(),
        "dispatch_results": [],
        "_meeting_id": meeting_id,
    }


def _api_client():
    from api import app
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DB layer — action_agent/db.py
# ═══════════════════════════════════════════════════════════════════════════════

async def test_db_module_importable():
    from action_agent import db  # noqa: F401
    assert db is not None


async def test_init_db_creates_tables():
    """init_db() creates meetings, tasks, channel_messages tables."""
    from action_agent.db import init_db, get_connection

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        async with get_connection(db_path) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        assert "meetings" in tables
        assert "tasks" in tables
        assert "channel_messages" in tables
    finally:
        os.unlink(db_path)


async def test_save_meeting_inserts_row():
    """save_meeting() inserts a row into the meetings table."""
    from action_agent.db import init_db, save_meeting, get_connection

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id="t-001", summary=_make_summary())
        async with get_connection(db_path) as conn:
            cursor = await conn.execute("SELECT id, thread_id, title FROM meetings")
            rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == meeting_id
        assert rows[0][1] == "t-001"
        assert rows[0][2] == "Sprint Planning"
    finally:
        os.unlink(db_path)


async def test_save_meeting_upserts_on_same_thread_id():
    """Calling save_meeting twice with the same thread_id upserts (no duplicate)."""
    from action_agent.db import init_db, save_meeting, get_connection

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        id1 = await save_meeting(db_path, thread_id="t-dupe", summary=_make_summary())
        id2 = await save_meeting(db_path, thread_id="t-dupe", summary=_make_summary())
        async with get_connection(db_path) as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM meetings WHERE thread_id='t-dupe'")
            count = (await cursor.fetchone())[0]
        assert count == 1
        assert id1 == id2
    finally:
        os.unlink(db_path)


async def test_save_tasks_inserts_all_items():
    """save_tasks() inserts one row per ActionItem."""
    from action_agent.db import init_db, save_meeting, save_tasks, get_connection
    from action_agent.models.schemas import ActionItem, ValidationResult

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id="t-tasks", summary=_make_summary())
        vr = _make_items()
        await save_tasks(db_path, meeting_id=meeting_id, validation_result=vr)

        async with get_connection(db_path) as conn:
            cursor = await conn.execute("SELECT id, description, owner, deadline FROM tasks")
            rows = await cursor.fetchall()
        assert len(rows) == 2
        descriptions = {r[1] for r in rows}
        assert "Write docs" in descriptions
        assert "Fix bug" in descriptions
    finally:
        os.unlink(db_path)


async def test_save_tasks_sets_default_status_todo():
    """Newly saved tasks have status='todo'."""
    from action_agent.db import init_db, save_meeting, save_tasks, get_connection

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id="t-status", summary=_make_summary())
        await save_tasks(db_path, meeting_id=meeting_id, validation_result=_make_items())

        async with get_connection(db_path) as conn:
            cursor = await conn.execute("SELECT status FROM tasks")
            rows = await cursor.fetchall()
        assert all(r[0] == "todo" for r in rows)
    finally:
        os.unlink(db_path)


async def test_save_channel_message_inserts_row():
    """save_channel_message() inserts a row into channel_messages."""
    from action_agent.db import init_db, save_meeting, save_channel_message, get_connection

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id="t-chan", summary=_make_summary())
        await save_channel_message(db_path, meeting_id=meeting_id, content="Hello team!")

        async with get_connection(db_path) as conn:
            cursor = await conn.execute("SELECT content, meeting_id FROM channel_messages")
            rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "Hello team!"
        assert rows[0][1] == meeting_id
    finally:
        os.unlink(db_path)


async def test_get_tasks_returns_all():
    """get_tasks() with no filters returns all tasks."""
    from action_agent.db import init_db, save_meeting, save_tasks, get_tasks

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id="t-get", summary=_make_summary())
        await save_tasks(db_path, meeting_id=meeting_id, validation_result=_make_items())

        tasks = await get_tasks(db_path)
        assert len(tasks) == 2
        assert all("description" in t for t in tasks)
    finally:
        os.unlink(db_path)


async def test_get_tasks_filter_by_status():
    """get_tasks(status='todo') returns only tasks with that status."""
    from action_agent.db import init_db, save_meeting, save_tasks, get_tasks, update_task

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id="t-filter", summary=_make_summary())
        await save_tasks(db_path, meeting_id=meeting_id, validation_result=_make_items())

        # Move first task to in_progress
        tasks = await get_tasks(db_path)
        await update_task(db_path, task_id=tasks[0]["id"], status="in_progress")

        todo = await get_tasks(db_path, status="todo")
        assert len(todo) == 1
        assert todo[0]["status"] == "todo"
    finally:
        os.unlink(db_path)


async def test_get_tasks_filter_by_owner():
    """get_tasks(owner='Alice Smith') returns only Alice's tasks."""
    from action_agent.db import init_db, save_meeting, save_tasks, get_tasks

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id="t-owner", summary=_make_summary())
        await save_tasks(db_path, meeting_id=meeting_id, validation_result=_make_items())

        alice_tasks = await get_tasks(db_path, owner="Alice Smith")
        assert len(alice_tasks) == 1
        assert alice_tasks[0]["owner"] == "Alice Smith"
    finally:
        os.unlink(db_path)


async def test_get_tasks_filter_by_meeting_id():
    """get_tasks(meeting_id=X) returns only tasks for that meeting."""
    from action_agent.db import init_db, save_meeting, save_tasks, get_tasks

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        m1 = await save_meeting(db_path, thread_id="t-m1", summary=_make_summary())
        m2 = await save_meeting(db_path, thread_id="t-m2", summary=_make_summary())
        await save_tasks(db_path, meeting_id=m1, validation_result=_make_items())
        await save_tasks(db_path, meeting_id=m2, validation_result=_make_items())

        m1_tasks = await get_tasks(db_path, meeting_id=m1)
        assert len(m1_tasks) == 2
        assert all(t["meeting_id"] == m1 for t in m1_tasks)
    finally:
        os.unlink(db_path)


async def test_update_task_changes_status():
    """update_task() changes the status field of a task."""
    from action_agent.db import init_db, save_meeting, save_tasks, get_tasks, update_task

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id="t-update", summary=_make_summary())
        await save_tasks(db_path, meeting_id=meeting_id, validation_result=_make_items())

        tasks = await get_tasks(db_path)
        task_id = tasks[0]["id"]
        await update_task(db_path, task_id=task_id, status="done")

        updated = await get_tasks(db_path)
        target = next(t for t in updated if t["id"] == task_id)
        assert target["status"] == "done"
    finally:
        os.unlink(db_path)


async def test_get_meetings_returns_all():
    """get_meetings() returns all meeting rows newest first."""
    from action_agent.db import init_db, save_meeting, get_meetings

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        await save_meeting(db_path, thread_id="t-a", summary=_make_summary())
        await save_meeting(db_path, thread_id="t-b", summary=_make_summary())

        meetings = await get_meetings(db_path)
        assert len(meetings) == 2
        assert all("id" in m for m in meetings)
        assert all("title" in m for m in meetings)
    finally:
        os.unlink(db_path)


async def test_get_channel_returns_newest_first():
    """get_channel() returns channel_messages newest first."""
    from action_agent.db import init_db, save_meeting, save_channel_message, get_channel
    import asyncio

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id="t-ch-order", summary=_make_summary())
        await save_channel_message(db_path, meeting_id=meeting_id, content="First message")
        await asyncio.sleep(0.01)
        await save_channel_message(db_path, meeting_id=meeting_id, content="Second message")

        messages = await get_channel(db_path)
        assert len(messages) == 2
        assert messages[0]["content"] == "Second message"  # newest first
    finally:
        os.unlink(db_path)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. dispatch_local_node
# ═══════════════════════════════════════════════════════════════════════════════

async def test_dispatch_local_node_importable():
    from action_agent.graph.nodes import dispatch_local_node  # noqa: F401
    assert dispatch_local_node is not None


async def test_dispatch_local_returns_local_tool():
    """dispatch_local_node returns DispatchResult with tool='local'."""
    from action_agent.graph.nodes import dispatch_local_node

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        result = await dispatch_local_node(state, {"configurable": {}}, db_path=db_path)
        assert len(result["dispatch_results"]) == 1
        assert result["dispatch_results"][0].tool == "local"
        assert result["dispatch_results"][0].success is True
    finally:
        os.unlink(db_path)


async def test_dispatch_local_saves_tasks_to_db():
    """dispatch_local_node persists action items as tasks in the DB."""
    from action_agent.graph.nodes import dispatch_local_node
    from action_agent.db import get_tasks

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        await dispatch_local_node(state, {"configurable": {}}, db_path=db_path)
        tasks = await get_tasks(db_path)
        assert len(tasks) == 2
    finally:
        os.unlink(db_path)


async def test_dispatch_local_saves_meeting_to_db():
    """dispatch_local_node persists the meeting summary."""
    from action_agent.graph.nodes import dispatch_local_node
    from action_agent.db import get_meetings

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        await dispatch_local_node(state, {"configurable": {}}, db_path=db_path)
        meetings = await get_meetings(db_path)
        assert len(meetings) == 1
        assert meetings[0]["title"] == "Sprint Planning"
    finally:
        os.unlink(db_path)


async def test_dispatch_local_saves_channel_message():
    """dispatch_local_node creates a channel message for the meeting broadcast."""
    from action_agent.graph.nodes import dispatch_local_node
    from action_agent.db import get_channel

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        await dispatch_local_node(state, {"configurable": {}}, db_path=db_path)
        messages = await get_channel(db_path)
        assert len(messages) == 1
        # Channel message should mention tasks
        assert "Write docs" in messages[0]["content"] or "Fix bug" in messages[0]["content"]
    finally:
        os.unlink(db_path)


async def test_dispatch_local_returns_meeting_id_as_item_id():
    """The dispatch result item_id is the meeting's DB id."""
    from action_agent.graph.nodes import dispatch_local_node
    from action_agent.db import get_meetings

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        state = _make_state()
        result = await dispatch_local_node(state, {"configurable": {}}, db_path=db_path)
        meetings = await get_meetings(db_path)
        assert result["dispatch_results"][0].item_id == meetings[0]["id"]
    finally:
        os.unlink(db_path)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. New API endpoints
# ═══════════════════════════════════════════════════════════════════════════════

async def test_get_tasks_endpoint_returns_list():
    """GET /tasks returns a JSON list."""
    async with _api_client() as client:
        resp = await client.get("/tasks")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_meetings_endpoint_returns_list():
    """GET /meetings returns a JSON list."""
    async with _api_client() as client:
        resp = await client.get("/meetings")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_channel_endpoint_returns_list():
    """GET /channel returns a JSON list."""
    async with _api_client() as client:
        resp = await client.get("/channel")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_patch_task_invalid_id_returns_404():
    """PATCH /tasks/{id} with a non-existent id returns 404."""
    async with _api_client() as client:
        resp = await client.patch(
            "/tasks/nonexistent-task-id",
            json={"status": "done"},
        )
    assert resp.status_code == 404


async def test_get_meetings_single_returns_404_for_unknown():
    """GET /meetings/{id} returns 404 for an unknown meeting id."""
    async with _api_client() as client:
        resp = await client.get("/meetings/no-such-meeting")
    assert resp.status_code == 404


async def test_get_tasks_filter_by_status_query_param():
    """GET /tasks?status=todo returns only todo tasks."""
    async with _api_client() as client:
        resp = await client.get("/tasks?status=todo")
    assert resp.status_code == 200
    tasks = resp.json()
    assert all(t["status"] == "todo" for t in tasks)


async def test_debrief_creates_tasks_and_meetings():
    """After POST /debrief, GET /tasks and GET /meetings return non-empty data."""
    SHORT = "Alice: Fix the login bug by Friday. Bob: Sure, I'll do it."
    async with _api_client() as client:
        resp = await client.post(
            "/debrief",
            json={"transcript": SHORT, "team_members": ["Alice", "Bob"]},
            timeout=120,
        )
    assert resp.status_code == 200

    async with _api_client() as client:
        tasks_resp = await client.get("/tasks")
        meetings_resp = await client.get("/meetings")
        channel_resp = await client.get("/channel")

    assert len(tasks_resp.json()) > 0
    assert len(meetings_resp.json()) > 0
    assert len(channel_resp.json()) > 0


async def test_dispatch_result_tool_is_local():
    """POST /debrief dispatch_results should have tool='local', not notion/jira/slack."""
    SHORT = "Bob: Update the README by Monday."
    async with _api_client() as client:
        resp = await client.post(
            "/debrief",
            json={"transcript": SHORT, "team_members": ["Bob"]},
            timeout=120,
        )
    body = resp.json()
    tool_names = {r["tool"] for r in body["dispatch_results"]}
    assert "local" in tool_names
    assert "notion" not in tool_names
    assert "jira" not in tool_names
    assert "slack" not in tool_names


async def test_graph_has_dispatch_local_node():
    """build_graph() includes 'dispatch_local' node, not notion/jira/slack nodes."""
    from action_agent.graph.builder import build_graph
    graph = build_graph()
    node_names = set(graph.nodes.keys())
    assert "dispatch_local" in node_names
    assert "dispatch_notion" not in node_names
    assert "dispatch_jira" not in node_names
    assert "dispatch_slack" not in node_names
