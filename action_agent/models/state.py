from __future__ import annotations
import operator
from typing import Annotated, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from action_agent.models.schemas import (
    MeetingSummary,
    ActionItem,
    ValidationResult,
    DispatchResult,
)


def _replace(existing: list, new: list) -> list:
    """Last-write-wins reducer — replaces the list rather than appending."""
    return new if new is not None else existing


class MeetingDebriefState(TypedDict):
    # ── Input ──────────────────────────────────────────────────────────────
    transcript: str
    team_members: list[str]

    # ── Message trace (append-only) ────────────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]

    # ── Pipeline outputs ───────────────────────────────────────────────────
    summary: Optional[MeetingSummary]
    raw_action_items: Annotated[list[ActionItem], _replace]
    assigned_action_items: Annotated[list[ActionItem], _replace]
    validation_result: Optional[ValidationResult]
    validation_attempts: int

    # dispatch_results appends across parallel nodes
    dispatch_results: Annotated[list[DispatchResult], operator.add]

    # ── Pipeline control ───────────────────────────────────────────────────
    error: Optional[str]
    status: str  # 'running' | 'complete' | 'error'
