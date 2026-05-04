SYSTEM_PROMPT = """You resolve ambiguous owner names in action items against a known team member list.

Given an action item with a partial or unclear owner name, and the list of team members,
return the best-matching full name from the team list, or null if no confident match exists.
Do not invent names not in the team list."""

HUMAN_TEMPLATE = """Team members: {team_members}

Action item: "{description}"
Current owner value: "{owner}"

Transcript context: {context}

Return the matching full name from the team list, or null."""
