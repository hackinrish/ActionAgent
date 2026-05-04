from action_agent.models.schemas import ActionItem, ValidationResult


class ValidationAgent:
    """Rule-based quality gate — no LLM calls."""

    REQUIRED_FIELDS = ("owner", "deadline")

    def run(
        self,
        items: list[ActionItem],
        attempt: int,
        max_attempts: int = 3,
    ) -> ValidationResult:
        valid: list[ActionItem] = []
        flagged: list[ActionItem] = []

        for item in items:
            missing = [f for f in self.REQUIRED_FIELDS if getattr(item, f) is None]
            if missing:
                item = item.model_copy(update={
                    "needs_clarification": True,
                    "clarification_reason": f"Missing: {', '.join(missing)}",
                })
                flagged.append(item)
            else:
                valid.append(item)

        # Force-complete at max attempts so nothing is silently dropped
        is_complete = (not flagged) or (attempt >= max_attempts)
        return ValidationResult(
            valid_items=valid,
            flagged_items=flagged,
            is_complete=is_complete,
        )
