from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from action_agent.models.schemas import MeetingSummary
from action_agent.prompts.summarizer import SYSTEM_PROMPT, HUMAN_TEMPLATE


def _get_llm() -> ChatAnthropic:
    from action_agent.config import settings
    return ChatAnthropic(
        model=settings.claude_model,
        temperature=settings.claude_temperature,
        anthropic_api_key=settings.anthropic_api_key or None,
    )


class SummarizerAgent:
    async def run(self, transcript: str) -> MeetingSummary:
        llm = _get_llm().with_structured_output(MeetingSummary)
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", HUMAN_TEMPLATE),
        ])
        chain = prompt | llm
        return await chain.ainvoke({"transcript": transcript})
