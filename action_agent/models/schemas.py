from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ActionItem(BaseModel):
    id: str
    description: str
    owner: Optional[str] = None
    deadline: Optional[str] = None
    priority: Priority = Priority.MEDIUM
    context: Optional[str] = None
    needs_clarification: bool = False
    clarification_reason: Optional[str] = None


class MeetingSummary(BaseModel):
    title: str
    date: Optional[str] = None
    participants: list[str] = Field(default_factory=list)
    key_decisions: list[str] = Field(default_factory=list)
    summary: str
    next_meeting: Optional[str] = None


class ValidationResult(BaseModel):
    valid_items: list[ActionItem] = Field(default_factory=list)
    flagged_items: list[ActionItem] = Field(default_factory=list)
    is_complete: bool = False


class DispatchResult(BaseModel):
    tool: str
    success: bool
    item_id: Optional[str] = None
    error_message: Optional[str] = None
