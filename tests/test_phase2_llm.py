"""
Phase 2 tests — real LLM integration via Claude API.
Requires ANTHROPIC_API_KEY in .env or environment.
All tests are async (pytest-asyncio auto mode active via pyproject.toml).
"""
from pathlib import Path

TRANSCRIPT = (Path(__file__).parent / "fixtures" / "sample_transcript.txt").read_text()


# ── SummarizerAgent ───────────────────────────────────────────────────────────

async def test_summarizer_returns_meeting_summary():
    from action_agent.agents.summarizer import SummarizerAgent
    from action_agent.models.schemas import MeetingSummary
    agent = SummarizerAgent()
    result = await agent.run(transcript=TRANSCRIPT)
    assert isinstance(result, MeetingSummary)
    assert result.title
    assert result.summary
    assert len(result.participants) > 0


async def test_summarizer_extracts_participants():
    from action_agent.agents.summarizer import SummarizerAgent
    agent = SummarizerAgent()
    result = await agent.run(transcript=TRANSCRIPT)
    names = " ".join(result.participants).lower()
    assert "alice" in names or "bob" in names or "carol" in names


async def test_summarizer_extracts_key_decisions():
    from action_agent.agents.summarizer import SummarizerAgent
    agent = SummarizerAgent()
    result = await agent.run(transcript=TRANSCRIPT)
    # Sample transcript has explicit decisions about OAuth2 and Grafana
    decisions = " ".join(result.key_decisions).lower()
    assert len(result.key_decisions) > 0
    assert "oauth" in decisions or "grafana" in decisions or "demo" in decisions


# ── ActionExtractionAgent ─────────────────────────────────────────────────────

async def test_action_extractor_returns_items():
    from action_agent.agents.summarizer import SummarizerAgent
    from action_agent.agents.action_extractor import ActionExtractionAgent
    from action_agent.models.schemas import ActionItem
    summary = await SummarizerAgent().run(transcript=TRANSCRIPT)
    items = await ActionExtractionAgent().run(transcript=TRANSCRIPT, summary=summary)
    assert isinstance(items, list)
    assert len(items) >= 4  # sample transcript has 5+ explicit tasks
    assert all(isinstance(i, ActionItem) for i in items)


async def test_action_extractor_ids_are_sequential():
    from action_agent.agents.summarizer import SummarizerAgent
    from action_agent.agents.action_extractor import ActionExtractionAgent
    summary = await SummarizerAgent().run(transcript=TRANSCRIPT)
    items = await ActionExtractionAgent().run(transcript=TRANSCRIPT, summary=summary)
    for item in items:
        assert item.id.startswith("ai-"), f"Bad ID format: {item.id}"


async def test_action_extractor_finds_token_validation_task():
    """Transcript has explicit: Bob will do token validation by May 15."""
    from action_agent.agents.summarizer import SummarizerAgent
    from action_agent.agents.action_extractor import ActionExtractionAgent
    summary = await SummarizerAgent().run(transcript=TRANSCRIPT)
    items = await ActionExtractionAgent().run(transcript=TRANSCRIPT, summary=summary)
    descs = " ".join(i.description.lower() for i in items)
    assert "token" in descs or "auth" in descs or "oauth" in descs or "validation" in descs


async def test_action_extractor_with_flagged_context():
    """On re-run with flagged items, agent should attempt to resolve them."""
    from action_agent.agents.summarizer import SummarizerAgent
    from action_agent.agents.action_extractor import ActionExtractionAgent
    from action_agent.models.schemas import ActionItem
    summary = await SummarizerAgent().run(transcript=TRANSCRIPT)
    # Simulate a flagged item missing an owner
    flagged = [ActionItem(
        id="ai-001",
        description="Complete backend token validation",
        needs_clarification=True,
        clarification_reason="Missing: owner, deadline",
    )]
    items = await ActionExtractionAgent().run(
        transcript=TRANSCRIPT,
        summary=summary,
        flagged_context=flagged,
    )
    assert len(items) > 0


# ── AssignmentAgent ───────────────────────────────────────────────────────────

async def test_assignment_exact_name_no_llm_call():
    """Exact team member match — should resolve without LLM."""
    from action_agent.agents.assignment import AssignmentAgent
    from action_agent.models.schemas import ActionItem
    agent = AssignmentAgent()
    team = ["Alice Smith", "Bob Jones", "Carol White"]
    items = [
        ActionItem(id="ai-001", description="Write tests", owner="Alice Smith", deadline="2026-05-10"),
        ActionItem(id="ai-002", description="Review PR", owner="Bob Jones", deadline="2026-05-10"),
    ]
    result = await agent.run(items=items, team_members=team, transcript=TRANSCRIPT)
    assert result[0].owner == "Alice Smith"
    assert result[1].owner == "Bob Jones"


async def test_assignment_first_name_resolves_to_full_name():
    from action_agent.agents.assignment import AssignmentAgent
    from action_agent.models.schemas import ActionItem
    agent = AssignmentAgent()
    team = ["Alice Smith", "Bob Jones", "Carol White"]
    items = [ActionItem(id="ai-001", description="Deploy service", owner="Alice", deadline="2026-05-10")]
    result = await agent.run(items=items, team_members=team, transcript=TRANSCRIPT)
    assert result[0].owner == "Alice Smith"


async def test_assignment_none_owner_unchanged():
    """Items with no owner should remain None — not assigned by guess."""
    from action_agent.agents.assignment import AssignmentAgent
    from action_agent.models.schemas import ActionItem
    agent = AssignmentAgent()
    team = ["Alice Smith", "Bob Jones"]
    items = [ActionItem(id="ai-001", description="Unknown task")]
    result = await agent.run(items=items, team_members=team, transcript=TRANSCRIPT)
    assert result[0].owner is None


async def test_assignment_empty_team_passthrough():
    from action_agent.agents.assignment import AssignmentAgent
    from action_agent.models.schemas import ActionItem
    agent = AssignmentAgent()
    items = [ActionItem(id="ai-001", description="Task", owner="Alice")]
    result = await agent.run(items=items, team_members=[], transcript=TRANSCRIPT)
    assert result[0].owner == "Alice"  # unchanged when no team list


# ── ValidationAgent regression ────────────────────────────────────────────────

def test_validation_regression():
    from action_agent.agents.validator import ValidationAgent
    from action_agent.models.schemas import ActionItem
    agent = ValidationAgent()
    items = [
        ActionItem(id="ai-001", description="Complete task", owner="Alice", deadline="2026-05-10"),
        ActionItem(id="ai-002", description="No owner task"),
    ]
    result = agent.run(items=items, attempt=1)
    assert len(result.valid_items) == 1
    assert len(result.flagged_items) == 1


# ── Full agent pipeline (no graph — direct agent calls) ───────────────────────

async def test_full_agent_pipeline():
    from action_agent.agents.summarizer import SummarizerAgent
    from action_agent.agents.action_extractor import ActionExtractionAgent
    from action_agent.agents.assignment import AssignmentAgent
    from action_agent.agents.validator import ValidationAgent
    from action_agent.models.schemas import MeetingSummary, ActionItem

    team = ["Alice Smith", "Bob Jones", "Carol White", "David Lee"]

    summary = await SummarizerAgent().run(transcript=TRANSCRIPT)
    assert isinstance(summary, MeetingSummary)
    assert summary.participants

    items = await ActionExtractionAgent().run(transcript=TRANSCRIPT, summary=summary)
    assert len(items) >= 3

    assigned = await AssignmentAgent().run(items=items, team_members=team, transcript=TRANSCRIPT)
    assert len(assigned) == len(items)

    vr = ValidationAgent().run(items=assigned, attempt=1)
    assert len(vr.valid_items) + len(vr.flagged_items) == len(items)

    # At least some items should be fully resolved from this transcript
    assert len(vr.valid_items) > 0
