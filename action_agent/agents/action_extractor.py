from pydantic import BaseModel
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from action_agent.models.schemas import ActionItem, MeetingSummary
from action_agent.prompts.action_extractor import (
    SYSTEM_PROMPT,
    HUMAN_TEMPLATE,
    format_flagged_hint,
)


class ActionExtractionResponse(BaseModel):
    action_items: list[ActionItem]


def _get_llm() -> ChatAnthropic:
    from action_agent.config import settings
    return ChatAnthropic(
        model=settings.claude_model,
        temperature=settings.claude_temperature,
        anthropic_api_key=settings.anthropic_api_key or None,
    )


class ActionExtractionAgent:
    async def run(
        self,
        transcript: str,
        summary: MeetingSummary,
        flagged_context: list[ActionItem] | None = None,
    ) -> list[ActionItem]:
        llm = _get_llm().with_structured_output(ActionExtractionResponse)
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", HUMAN_TEMPLATE),
        ])
        chain = prompt | llm
        result = await chain.ainvoke({
            "transcript": transcript,
            "decisions": "\n".join(summary.key_decisions) if summary else "",
            "participants": ", ".join(summary.participants) if summary else "",
            "flagged_hint": format_flagged_hint(flagged_context),
        })
        return result.action_items
