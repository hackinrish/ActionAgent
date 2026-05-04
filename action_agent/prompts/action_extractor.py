SYSTEM_PROMPT = """You are an expert at extracting action items from meeting transcripts.

Rules:
- Extract every task, follow-up, or commitment mentioned
- Assign sequential IDs: ai-001, ai-002, ...
- owner: person responsible (first + last name if mentioned); null if unclear
- deadline: specific date or relative (e.g. "end of week"); null if not stated
- context: verbatim quote from transcript that implies this action
- Set needs_clarification=false — ValidationAgent handles that downstream

When re-running with flagged items, focus on resolving the missing owner/deadline
by searching the transcript more carefully."""

HUMAN_TEMPLATE = """Key decisions: {decisions}
Participants: {participants}

{flagged_hint}

Transcript:
{transcript}"""


def format_flagged_hint(flagged_items) -> str:
    if not flagged_items:
        return ""
    lines = ["Previously flagged items needing resolution:"]
    for item in flagged_items:
        lines.append(f"  - [{item.id}] {item.description} (missing: {item.clarification_reason})")
    return "\n".join(lines) + "\n"
