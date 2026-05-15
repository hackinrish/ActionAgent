import asyncio
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


def _format_slack_message(summary, items: list[ActionItem]) -> str:
    lines = ["*Meeting Debrief — Action Items*"]
    if summary:
        lines.append(f"_{summary.title}_\n")
    for item in items:
        flag = " NEEDS CLARIFICATION" if item.needs_clarification else ""
        owner = item.owner or "Unassigned"
        deadline = item.deadline or "No deadline"
        lines.append(f"• [{item.id}] {item.description}")
        lines.append(f"  Owner: {owner} | Due: {deadline} | Priority: {item.priority.value}{flag}")
    return "\n".join(lines)


async def dispatch_notion_node(state: dict, config: RunnableConfig) -> dict:
    from action_agent.config import settings
    items = _items_from_state(state)
    results: list[DispatchResult] = []

    if not settings.notion_api_key or not settings.notion_database_id:
        for item in items:
            results.append(DispatchResult(tool="notion", success=True, item_id=f"dry-run-{item.id}"))
        return {"dispatch_results": results or [DispatchResult(tool="notion", success=True, item_id="dry-run")]}

    from notion_client import AsyncClient
    client = AsyncClient(auth=settings.notion_api_key)
    for item in items:
        try:
            props: dict = {
                "Name": {"title": [{"text": {"content": item.description}}]},
                "Owner": {"rich_text": [{"text": {"content": item.owner or ""}}]},
                "Priority": {"select": {"name": item.priority.value.capitalize()}},
            }
            if item.deadline:
                props["Deadline"] = {"date": {"start": item.deadline}}
            page = await client.pages.create(
                parent={"database_id": settings.notion_database_id},
                properties=props,
            )
            results.append(DispatchResult(tool="notion", success=True, item_id=page["id"]))
        except Exception as exc:
            results.append(DispatchResult(tool="notion", success=False, error_message=str(exc)))

    return {"dispatch_results": results or [DispatchResult(tool="notion", success=True, item_id="notion-empty")]}


async def dispatch_jira_node(state: dict, config: RunnableConfig) -> dict:
    from action_agent.config import settings
    items = _items_from_state(state)
    results: list[DispatchResult] = []

    if not settings.jira_url or not settings.jira_api_token:
        for item in items:
            results.append(DispatchResult(tool="jira", success=True, item_id=f"DRY-{item.id}"))
        return {"dispatch_results": results or [DispatchResult(tool="jira", success=True, item_id="DRY-empty")]}

    from jira import JIRA
    jira_client = JIRA(
        server=settings.jira_url,
        basic_auth=(settings.jira_email, settings.jira_api_token),
    )
    for item in items:
        try:
            issue = await asyncio.to_thread(
                jira_client.create_issue,
                fields={
                    "project": {"key": settings.jira_project_key},
                    "summary": item.description,
                    "description": item.context or item.description,
                    "issuetype": {"name": "Task"},
                },
            )
            results.append(DispatchResult(tool="jira", success=True, item_id=issue.key))
        except Exception as exc:
            results.append(DispatchResult(tool="jira", success=False, error_message=str(exc)))

    return {"dispatch_results": results or [DispatchResult(tool="jira", success=True, item_id="PROJ-empty")]}


async def dispatch_slack_node(state: dict, config: RunnableConfig) -> dict:
    from action_agent.config import settings
    items = _items_from_state(state)
    message = _format_slack_message(state.get("summary"), items)

    if not settings.slack_bot_token:
        return {"dispatch_results": [DispatchResult(tool="slack", success=True, item_id="dry-run-slack")]}

    from slack_sdk.web.async_client import AsyncWebClient
    client = AsyncWebClient(token=settings.slack_bot_token)
    try:
        resp = await client.chat_postMessage(channel=settings.slack_channel, text=message)
        return {"dispatch_results": [DispatchResult(
            tool="slack", success=resp["ok"], item_id=resp.get("ts", "sent")
        )]}
    except Exception as exc:
        return {"dispatch_results": [DispatchResult(tool="slack", success=False, error_message=str(exc))]}


async def aggregate_dispatch_node(state: MeetingDebriefState, config: RunnableConfig) -> dict:
    results = state.get("dispatch_results", [])
    failures = [r for r in results if not r.success]
    status = "error" if failures else "complete"
    return {"status": status, "dispatch_results": results}
