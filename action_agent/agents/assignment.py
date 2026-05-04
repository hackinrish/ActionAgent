from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from action_agent.models.schemas import ActionItem
from action_agent.prompts.assignment import SYSTEM_PROMPT, HUMAN_TEMPLATE


def _get_llm() -> ChatAnthropic:
    from action_agent.config import settings
    return ChatAnthropic(
        model=settings.claude_model,
        temperature=0.0,
        anthropic_api_key=settings.anthropic_api_key or None,
    )


class AssignmentAgent:
    async def run(
        self,
        items: list[ActionItem],
        team_members: list[str],
        transcript: str,
    ) -> list[ActionItem]:
        if not team_members:
            return items

        resolved = []
        for item in items:
            if item.owner is None:
                resolved.append(item)
                continue

            matched = _fuzzy_match(item.owner, team_members)
            if matched:
                resolved.append(item.model_copy(update={"owner": matched}))
            else:
                # LLM fallback for ambiguous partial names
                owner = await _llm_resolve(item, team_members, transcript)
                resolved.append(item.model_copy(update={"owner": owner}))

        return resolved


def _fuzzy_match(name: str, team_members: list[str]) -> str | None:
    """Case-insensitive exact or first/last name match — no LLM needed."""
    name_lower = name.lower().strip()
    for member in team_members:
        if name_lower == member.lower():
            return member
        parts = member.lower().split()
        if any(name_lower == part for part in parts):
            return member
    return None


async def _llm_resolve(
    item: ActionItem,
    team_members: list[str],
    transcript: str,
) -> str | None:
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_TEMPLATE),
    ])
    chain = prompt | _get_llm()
    result = await chain.ainvoke({
        "team_members": ", ".join(team_members),
        "description": item.description,
        "owner": item.owner or "",
        "context": item.context or "",
    })
    text = result.content.strip()
    return _fuzzy_match(text, team_members)
