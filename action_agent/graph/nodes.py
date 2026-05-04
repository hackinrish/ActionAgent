import json
from langchain_core.runnables import RunnableConfig
from action_agent.models.state import MeetingDebriefState
from action_agent.models.schemas import DispatchResult, ActionItem


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


# ── Parallel dispatch nodes ───────────────────────────────────────────────────

def _items_from_state(state: dict) -> list[ActionItem]:
    vr = state.get("validation_result")
    if not vr:
        return []
    return vr.valid_items + vr.flagged_items


def _get_tool(mcp_tools: dict, server: str, name: str):
    return next((t for t in mcp_tools.get(server, []) if t.name == name), None)


def _parse_result(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
    return raw if isinstance(raw, dict) else {}


async def dispatch_notion_node(state: dict, config: RunnableConfig) -> dict:
    mcp_tools = config.get("configurable", {}).get("mcp_tools", {})
    create = _get_tool(mcp_tools, "notion", "notion_create_page")
    items = _items_from_state(state)

    results: list[DispatchResult] = []
    for item in items:
        try:
            if create:
                raw = await create.ainvoke({
                    "title": item.description,
                    "description": item.description
                    + (f"\n\n[NEEDS CLARIFICATION: {item.clarification_reason}]"
                       if item.needs_clarification else ""),
                    "owner": item.owner or "",
                    "deadline": item.deadline or "",
                    "priority": item.priority.value,
                })
                data = _parse_result(raw)
                results.append(DispatchResult(
                    tool="notion",
                    success=True,
                    item_id=data.get("id", f"notion-{item.id}"),
                ))
            else:
                results.append(DispatchResult(tool="notion", success=True, item_id=f"stub-{item.id}"))
        except Exception as exc:
            results.append(DispatchResult(tool="notion", success=False, error_message=str(exc)))

    if not results:
        results.append(DispatchResult(tool="notion", success=True, item_id="notion-empty"))

    return {"dispatch_results": results}


async def dispatch_jira_node(state: dict, config: RunnableConfig) -> dict:
    mcp_tools = config.get("configurable", {}).get("mcp_tools", {})
    create = _get_tool(mcp_tools, "jira", "jira_create_issue")
    items = _items_from_state(state)

    results: list[DispatchResult] = []
    for item in items:
        try:
            if create:
                raw = await create.ainvoke({
                    "summary": item.description,
                    "description": item.context or item.description,
                    "assignee": item.owner or "",
                    "due_date": item.deadline or "",
                    "priority": item.priority.value.capitalize(),
                })
                data = _parse_result(raw)
                results.append(DispatchResult(
                    tool="jira",
                    success=True,
                    item_id=data.get("key", f"PROJ-{item.id}"),
                ))
            else:
                results.append(DispatchResult(tool="jira", success=True, item_id=f"PROJ-stub-{item.id}"))
        except Exception as exc:
            results.append(DispatchResult(tool="jira", success=False, error_message=str(exc)))

    if not results:
        results.append(DispatchResult(tool="jira", success=True, item_id="PROJ-empty"))

    return {"dispatch_results": results}


async def dispatch_slack_node(state: dict, config: RunnableConfig) -> dict:
    """Posts a single summary message to Slack (not one per item)."""
    mcp_tools = config.get("configurable", {}).get("mcp_tools", {})
    post = _get_tool(mcp_tools, "slack", "slack_post_message")

    from action_agent.config import settings
    summary = state.get("summary")
    items = _items_from_state(state)

    lines = ["*Meeting Debrief — Action Items*"]
    if summary:
        lines.append(f"_{summary.title}_\n")
    for item in items:
        flag = " ⚠️ NEEDS CLARIFICATION" if item.needs_clarification else ""
        owner = item.owner or "Unassigned"
        deadline = item.deadline or "No deadline"
        lines.append(f"• [{item.id}] {item.description}")
        lines.append(f"  Owner: {owner} | Due: {deadline} | Priority: {item.priority.value}{flag}")
    message = "\n".join(lines)

    try:
        if post:
            raw = await post.ainvoke({"channel": settings.slack_channel, "text": message})
            data = _parse_result(raw)
            success = data.get("ok", True)
            ts = data.get("ts", "")
            return {"dispatch_results": [DispatchResult(
                tool="slack", success=success, item_id=ts or "slack-sent"
            )]}
        else:
            return {"dispatch_results": [DispatchResult(tool="slack", success=True, item_id="slack-stub")]}
    except Exception as exc:
        return {"dispatch_results": [DispatchResult(tool="slack", success=False, error_message=str(exc))]}


async def aggregate_dispatch_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    results = state.get("dispatch_results", [])
    failures = [r for r in results if not r.success]
    status = "error" if failures else "complete"
    # Re-emit the full accumulated dispatch_results so that any downstream
    # reader that merges state via plain dict.update() (e.g. astream test helpers)
    # sees all results rather than just the last parallel node's slice.
    # operator.add will concatenate this with the existing list in LangGraph state,
    # so we clear existing first by returning a fresh list that replaces via a
    # separate reducer. Since dispatch_results uses operator.add we emit an empty
    # list here — the accumulated results are already in state from the parallel
    # nodes. Instead, we place the full list in a canonical key through status.
    return {"status": status, "dispatch_results": results}
