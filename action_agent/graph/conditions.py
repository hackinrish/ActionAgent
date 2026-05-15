from action_agent.models.state import MeetingDebriefState


def route_after_validation(state: MeetingDebriefState) -> str:
    """
    After validation:
    - Loop back to extract_actions if flagged items remain and retries available.
    - Otherwise proceed to dispatch_local.
    """
    vr = state.get("validation_result")
    attempts = state.get("validation_attempts", 0)

    from action_agent.config import settings
    max_attempts = settings.max_validation_attempts

    if vr and vr.flagged_items and attempts < max_attempts:
        return "extract_actions"

    return "dispatch_local"
