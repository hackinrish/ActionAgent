"""
Phase 1 tests — skeleton, models, graph compilation, CLI.
All tests must pass before advancing to Phase 2.
"""
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


# ── Module imports ────────────────────────────────────────────────────────────

def test_schemas_import():
    from action_agent.models.schemas import (
        ActionItem, MeetingSummary, ValidationResult, DispatchResult, Priority,
    )


def test_state_import():
    from action_agent.models.state import MeetingDebriefState


def test_agents_import():
    from action_agent.agents.summarizer import SummarizerAgent
    from action_agent.agents.action_extractor import ActionExtractionAgent
    from action_agent.agents.assignment import AssignmentAgent
    from action_agent.agents.validator import ValidationAgent


def test_graph_import():
    from action_agent.graph.builder import build_graph
    from action_agent.graph.conditions import route_after_validation


def test_mcp_import():
    from action_agent.mcp.config import STUB_CONNECTIONS, ACTIVE_CONNECTIONS
    from action_agent.mcp.client import get_mcp_tools


# ── Pydantic model validation ─────────────────────────────────────────────────

def test_action_item_minimal():
    from action_agent.models.schemas import ActionItem, Priority
    item = ActionItem(id="ai-001", description="Write tests")
    assert item.owner is None
    assert item.deadline is None
    assert item.priority == Priority.MEDIUM
    assert item.needs_clarification is False


def test_action_item_full():
    from action_agent.models.schemas import ActionItem, Priority
    item = ActionItem(
        id="ai-002",
        description="Review PR",
        owner="Alice Smith",
        deadline="2026-05-10",
        priority=Priority.HIGH,
    )
    assert item.owner == "Alice Smith"
    assert item.priority == Priority.HIGH


def test_meeting_summary():
    from action_agent.models.schemas import MeetingSummary
    s = MeetingSummary(
        title="Sprint Planning",
        participants=["Alice", "Bob"],
        key_decisions=["Ship feature X by May"],
        summary="Team aligned on Q2 roadmap.",
    )
    assert len(s.participants) == 2
    assert s.next_meeting is None


def test_validation_result():
    from action_agent.models.schemas import ActionItem, ValidationResult
    item = ActionItem(id="ai-001", description="Deploy", owner="Bob", deadline="2026-05-15")
    vr = ValidationResult(valid_items=[item], flagged_items=[], is_complete=True)
    assert vr.is_complete
    assert len(vr.valid_items) == 1


def test_dispatch_result():
    from action_agent.models.schemas import DispatchResult
    dr = DispatchResult(tool="notion", success=True, item_id="notion-1234")
    assert dr.success
    assert dr.error_message is None


# ── State TypedDict construction ──────────────────────────────────────────────

def test_state_construction():
    from action_agent.models.state import MeetingDebriefState
    state: MeetingDebriefState = {
        "transcript": "Alice: Let's get started.",
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
    assert state["transcript"] == "Alice: Let's get started."
    assert state["status"] == "running"
    assert state["validation_attempts"] == 0


# ── Graph compilation ─────────────────────────────────────────────────────────

def test_build_graph():
    from action_agent.graph.builder import build_graph
    graph = build_graph()
    assert graph is not None


def test_graph_has_expected_nodes():
    from action_agent.graph.builder import build_graph
    graph = build_graph()
    node_names = set(graph.nodes.keys())
    for expected in (
        "summarize", "extract_actions", "assign_owners", "validate",
        "dispatch_notion", "dispatch_jira", "dispatch_slack", "aggregate_dispatch",
    ):
        assert expected in node_names, f"Missing node: {expected}"


# ── ValidationAgent (rule-based, no LLM) ─────────────────────────────────────

def test_validation_flags_missing_owner_and_deadline():
    from action_agent.agents.validator import ValidationAgent
    from action_agent.models.schemas import ActionItem
    agent = ValidationAgent()
    items = [ActionItem(id="ai-001", description="Write docs")]
    result = agent.run(items=items, attempt=1)
    assert len(result.flagged_items) == 1
    assert result.flagged_items[0].needs_clarification is True
    assert "owner" in result.flagged_items[0].clarification_reason
    assert result.is_complete is False


def test_validation_passes_complete_item():
    from action_agent.agents.validator import ValidationAgent
    from action_agent.models.schemas import ActionItem
    agent = ValidationAgent()
    items = [ActionItem(id="ai-001", description="Deploy", owner="Alice", deadline="2026-05-10")]
    result = agent.run(items=items, attempt=1)
    assert len(result.valid_items) == 1
    assert len(result.flagged_items) == 0
    assert result.is_complete is True


def test_validation_complete_at_max_attempts():
    from action_agent.agents.validator import ValidationAgent
    from action_agent.models.schemas import ActionItem
    agent = ValidationAgent()
    items = [ActionItem(id="ai-001", description="Write docs")]  # missing owner/deadline
    result = agent.run(items=items, attempt=3, max_attempts=3)
    assert result.is_complete is True  # force-complete at max retries


def test_validation_mixed_items():
    from action_agent.agents.validator import ValidationAgent
    from action_agent.models.schemas import ActionItem
    agent = ValidationAgent()
    items = [
        ActionItem(id="ai-001", description="Good", owner="Alice", deadline="2026-05-10"),
        ActionItem(id="ai-002", description="Bad"),  # missing both
    ]
    result = agent.run(items=items, attempt=1)
    assert len(result.valid_items) == 1
    assert len(result.flagged_items) == 1


# ── Stub MCP servers importable ───────────────────────────────────────────────

def test_notion_stub_importable():
    from action_agent.mcp.stubs import notion_stub
    assert notion_stub.mcp is not None


def test_jira_stub_importable():
    from action_agent.mcp.stubs import jira_stub
    assert jira_stub.mcp is not None


def test_slack_stub_importable():
    from action_agent.mcp.stubs import slack_stub
    assert slack_stub.mcp is not None


# ── CLI help ──────────────────────────────────────────────────────────────────

def test_cli_help():
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        capture_output=True, text=True,
        cwd=PROJECT_ROOT,
        env={**__import__("os").environ, "ANTHROPIC_API_KEY": "test-key"},
    )
    assert result.returncode == 0, f"CLI --help failed:\n{result.stderr}"
    output = result.stdout.lower()
    assert "transcript" in output or "meeting" in output or "debrief" in output
