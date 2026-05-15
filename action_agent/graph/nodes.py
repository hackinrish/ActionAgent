import uuid
from langchain_core.runnables import RunnableConfig

from action_agent.models.state import MeetingDebriefState
from action_agent.models.schemas import DispatchResult, ActionItem

_DEFAULT_DB = "local.db"


# ── Core pipeline nodes ───────────────────────────────────────────────────────

async def summarize_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    from action_agent.agents.summarizer import SummarizerAgent
    summary = await SummarizerAgent().run(transcript=state["transcript"])
    return {"summary": summary}


async def extract_actions_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    from action_agent.agents.action_extractor import ActionExtractionAgent
    vr = state.get("validation_result")
    flagged = vr.flagged_items if vr else None
    items = await ActionExtractionAgent().run(
        transcript=state["transcript"],
        summary=state["summary"],
        flagged_context=flagged,
    )
    return {"raw_action_items": items}


async def assign_owners_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    from action_agent.agents.assignment import AssignmentAgent
    items = await AssignmentAgent().run(
        items=state["raw_action_items"],
        team_members=state["team_members"],
        transcript=state["transcript"],
    )
    return {"assigned_action_items": items}


async def validate_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    from action_agent.agents.validator import ValidationAgent
    from action_agent.config import settings
    attempt = state.get("validation_attempts", 0) + 1
    result = ValidationAgent().run(
        items=state["assigned_action_items"],
        attempt=attempt,
        max_attempts=settings.max_validation_attempts,
    )
    return {"validation_result": result, "validation_attempts": attempt}


# ── Dispatch helpers ──────────────────────────────────────────────────────────

def _items_from_state(state: dict) -> list[ActionItem]:
    vr = state.get("validation_result")
    if not vr:
        return []
    return vr.valid_items + vr.flagged_items


def _format_channel_message(summary, items: list[ActionItem]) -> str:
    lines = ["*Meeting Debrief — Action Items*"]
    if summary:
        lines.append(f"_{summary.title}_\n")
    for item in items:
        flag = " [NEEDS CLARIFICATION]" if item.needs_clarification else ""
        owner = item.owner or "Unassigned"
        deadline = item.deadline or "No deadline"
        lines.append(f"• {item.description}")
        lines.append(f"  Owner: {owner} | Due: {deadline} | Priority: {item.priority.value}{flag}")
    return "\n".join(lines)


# ── Local dispatch node ───────────────────────────────────────────────────────

async def dispatch_local_node(
    state: dict,
    config: RunnableConfig,
    *,
    db_path: str = _DEFAULT_DB,
) -> dict:
    """Write meeting, tasks, and channel message to local SQLite DB."""
    from action_agent.db import (
        init_db, save_meeting, save_tasks, save_channel_message,
    )

    items = _items_from_state(state)
    summary = state.get("summary")

    # Use thread_id from config if available, otherwise generate
    thread_id = (
        (config or {}).get("configurable", {}).get("thread_id")
        or f"run-{uuid.uuid4().hex[:8]}"
    )

    try:
        await init_db(db_path)
        meeting_id = await save_meeting(db_path, thread_id=thread_id, summary=summary)
        from action_agent.models.schemas import ValidationResult
        vr = state.get("validation_result") or ValidationResult(
            valid_items=[], flagged_items=[], is_complete=True
        )
        await save_tasks(db_path, meeting_id=meeting_id, validation_result=vr)

        message = _format_channel_message(summary, items)
        await save_channel_message(db_path, meeting_id=meeting_id, content=message)

        return {"dispatch_results": [DispatchResult(tool="local", success=True, item_id=meeting_id)]}
    except Exception as exc:
        return {"dispatch_results": [DispatchResult(tool="local", success=False, error_message=str(exc))]}


async def aggregate_dispatch_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    results = state.get("dispatch_results", [])
    failures = [r for r in results if not r.success]
    status = "error" if failures else "complete"
    return {"status": status, "dispatch_results": results}
