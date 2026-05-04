from langgraph.types import Send
from action_agent.models.state import MeetingDebriefState


def route_after_validation(state: MeetingDebriefState):
    """
    After validation:
    - Loop back to extract_actions if flagged items remain and retries available.
    - Otherwise fan-out to parallel dispatch nodes via Send.
    """
    vr = state.get("validation_result")
    attempts = state.get("validation_attempts", 0)

    from action_agent.config import settings
    max_attempts = settings.max_validation_attempts

    if vr and vr.flagged_items and attempts < max_attempts:
        return "extract_actions"

    # Fan-out: all 3 dispatch nodes run in parallel
    return [
        Send("dispatch_notion", dict(state)),
        Send("dispatch_jira",   dict(state)),
        Send("dispatch_slack",  dict(state)),
    ]
