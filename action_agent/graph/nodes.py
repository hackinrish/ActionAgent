from langchain_core.runnables import RunnableConfig
from action_agent.models.state import MeetingDebriefState
from action_agent.models.schemas import DispatchResult


async def summarize_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    from action_agent.agents.summarizer import SummarizerAgent
    agent = SummarizerAgent()
    summary = await agent.run(transcript=state["transcript"])
    return {"summary": summary}


async def extract_actions_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    from action_agent.agents.action_extractor import ActionExtractionAgent
    agent = ActionExtractionAgent()
    vr = state.get("validation_result")
    flagged = vr.flagged_items if vr else None
    items = await agent.run(
        transcript=state["transcript"],
        summary=state["summary"],
        flagged_context=flagged,
    )
    return {"raw_action_items": items}


async def assign_owners_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    from action_agent.agents.assignment import AssignmentAgent
    agent = AssignmentAgent()
    items = await agent.run(
        items=state["raw_action_items"],
        team_members=state["team_members"],
        transcript=state["transcript"],
    )
    return {"assigned_action_items": items}


async def validate_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    from action_agent.agents.validator import ValidationAgent
    from action_agent.config import settings
    agent = ValidationAgent()
    attempt = state.get("validation_attempts", 0) + 1
    result = agent.run(
        items=state["assigned_action_items"],
        attempt=attempt,
        max_attempts=settings.max_validation_attempts,
    )
    return {
        "validation_result": result,
        "validation_attempts": attempt,
    }


async def dispatch_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    """
    Phase 1: stub dispatch — logs mock results for notion, jira, slack.
    Phase 3: replaced with real MCP tool calls via MultiServerMCPClient.
    """
    vr = state.get("validation_result")
    items = []
    if vr:
        items = vr.valid_items + vr.flagged_items

    results: list[DispatchResult] = []
    for i, item in enumerate(items):
        for tool in ("notion", "jira", "slack"):
            results.append(DispatchResult(
                tool=tool,
                success=True,
                item_id=f"stub-{tool}-{i + 1:03d}",
            ))

    # Ensure at least one result per tool even if no items
    if not results:
        for tool in ("notion", "jira", "slack"):
            results.append(DispatchResult(tool=tool, success=True, item_id=f"stub-{tool}-000"))

    return {
        "dispatch_results": results,
        "status": "complete",
    }
