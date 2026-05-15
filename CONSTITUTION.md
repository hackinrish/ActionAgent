# ActionAgent — Constitution

_This document is the authoritative source of truth for the ActionAgent system.
All implementation decisions, test cases, and architectural choices are derived from it.
When code and Constitution conflict, the Constitution wins — fix the code._

---

## 1. Mission Statement

ActionAgent transforms unstructured meeting transcripts into structured, dispatched work.
It ingests a raw transcript, runs a multi-agent LangGraph pipeline to extract and assign
action items, validates them, and pushes the results to Notion (task database), Jira
(issue tracker), and Slack (team broadcast) — without any manual post-meeting work.

**Success criterion:** Given a meeting transcript and a list of team members, the system
produces fully assigned, deadline-bearing action items and pushes them to all three
external services within one pipeline run, requiring no human intervention.

---

## 2. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| LLM | Anthropic Claude (claude-sonnet-4-6) | Best-in-class instruction following for structured extraction |
| Agent orchestration | LangGraph 0.5+ (StateGraph) | Native parallel fan-out via `Send`, built-in checkpointing |
| LLM client | langchain-anthropic + langchain-core | `with_structured_output` for schema-enforced extraction |
| Data validation | Pydantic v2 | Runtime schema enforcement, IDE-friendly |
| Config | pydantic-settings | `.env` + env var loading, typed settings |
| Notion integration | notion-client (AsyncClient) | Official Python SDK, async-native |
| Jira integration | jira (via asyncio.to_thread) | Mature REST wrapper; no async SDK exists |
| Slack integration | slack-sdk (AsyncWebClient) | Official async SDK |
| REST API | FastAPI | Async, SSE streaming, auto-docs |
| Web UI | Vanilla HTML/JS | No build step, SSE-native via EventSource |
| CLI | Typer + Rich | Clean UX, no boilerplate |
| Testing | pytest + pytest-asyncio (asyncio_mode=auto) | Async-first, fixtures |

**Not used:** MCP protocol, FastMCP stub servers, langchain-mcp-adapters.
Dispatch nodes call the external SDKs directly. When credentials are absent,
dispatch nodes run in dry-run mode and return synthetic success results.

---

## 3. Data Contracts

All schemas live in `action_agent/models/schemas.py`.

### ActionItem
```
id: str                    # sequential: "ai-001", "ai-002", …
description: str           # what must be done
owner: str | None          # full name matching team_members list
deadline: str | None       # ISO date "YYYY-MM-DD"
priority: Priority         # low | medium | high | critical
context: str | None        # supporting excerpt from transcript
needs_clarification: bool  # True when owner or deadline could not be resolved
clarification_reason: str | None
```
**Invariants:**
- `id` is unique within a run
- `needs_clarification=True` iff `owner is None or deadline is None` after max validation attempts
- Items with `needs_clarification=True` are dispatched with a `[NEEDS CLARIFICATION]` prefix; nothing is dropped

### MeetingSummary
```
title: str
date: str | None
participants: list[str]
key_decisions: list[str]
summary: str
next_meeting: str | None
```

### ValidationResult
```
valid_items: list[ActionItem]    # owner and deadline both set
flagged_items: list[ActionItem]  # missing owner or deadline
is_complete: bool                # True when no flagged items OR max attempts reached
```

### DispatchResult
```
tool: str          # "notion" | "jira" | "slack"
success: bool
item_id: str | None
error_message: str | None
```

---

## 4. LangGraph Pipeline

```
START
  └─► summarize
        └─► extract_actions
              └─► assign_owners
                    └─► validate
                          │
                          ├─[flagged items AND attempts < max]─► extract_actions (retry)
                          │
                          └─[valid OR max attempts reached]─► Send fan-out
                                                                   ├─► dispatch_notion ─┐
                                                                   ├─► dispatch_jira   ─┼─► aggregate_dispatch ─► END
                                                                   └─► dispatch_slack  ─┘
```

### Node contracts

| Node | Reads from state | Writes to state |
|---|---|---|
| `summarize` | `transcript` | `summary` |
| `extract_actions` | `transcript`, `summary`, `validation_result.flagged_items?` | `raw_action_items` |
| `assign_owners` | `raw_action_items`, `team_members`, `transcript` | `assigned_action_items` |
| `validate` | `assigned_action_items`, `validation_attempts` | `validation_result`, `validation_attempts` |
| `dispatch_notion` | `validation_result`, `summary` | `dispatch_results` (appended) |
| `dispatch_jira` | `validation_result` | `dispatch_results` (appended) |
| `dispatch_slack` | `validation_result`, `summary` | `dispatch_results` (appended) |
| `aggregate_dispatch` | `dispatch_results` | `status`, `dispatch_results` (normalized) |

### Dispatch behavior contract
- **With credentials** (`NOTION_API_KEY`, `JIRA_URL`, `SLACK_BOT_TOKEN` all set): calls real SDK
- **Without credentials (dry-run)**: returns `DispatchResult(success=True, item_id="dry-run-<id>")`
- **On SDK error**: returns `DispatchResult(success=False, error_message=<exc>)`
- Aggregate sets `status="error"` iff any dispatch has `success=False`; otherwise `status="complete"`

---

## 5. API Contracts

### `GET /health`
```json
{ "status": "ok", "version": "0.1.0" }
```

### `POST /debrief`
Request: `{ "transcript": str, "team_members": list[str] }`
Response: `{ "status": str, "summary": obj|null, "action_items": list, "dispatch_results": list }`

### `POST /debrief/jobs`
Request: same as above
Response: `{ "job_id": str }`

### `GET /debrief/jobs/{job_id}/stream`
SSE stream. Each event:
```
event: progress
data: {"node": "<node_name>", "status": "complete"}

event: complete
data: { <DebriefResponse fields> }

event: error
data: {"type": "error", "message": str}
```

### `GET /`
Returns `frontend/index.html` (HTML, 200).

---

## 6. Configuration

All settings read from `.env` via pydantic-settings.

| Key | Type | Required for |
|---|---|---|
| `ANTHROPIC_API_KEY` | str | Agent pipeline (any run) |
| `CLAUDE_MODEL` | str | Default: `claude-sonnet-4-6` |
| `TEAM_MEMBERS` | comma-str | Assignment agent fallback |
| `NOTION_API_KEY` | str | Live Notion dispatch |
| `NOTION_DATABASE_ID` | str | Live Notion dispatch |
| `JIRA_URL` | str | Live Jira dispatch |
| `JIRA_EMAIL` | str | Live Jira dispatch |
| `JIRA_API_TOKEN` | str | Live Jira dispatch |
| `JIRA_PROJECT_KEY` | str | Live Jira dispatch |
| `SLACK_BOT_TOKEN` | str | Live Slack dispatch |
| `SLACK_CHANNEL` | str | Default: `#meeting-debriefs` |
| `MAX_VALIDATION_ATTEMPTS` | int | Default: `3` |

Missing service credentials → dry-run mode for that service (not an error at startup).

---

## 7. Roadmap

Each phase follows this gate protocol:
1. Testing agent writes all tests for the phase **before any implementation**
2. Tests run → expected RED
3. Implementation written to satisfy tests
4. All tests GREEN → commit + push
5. Roadmap updated; next phase begins

---

### Phase 1 — Foundation [COMPLETE ✅]
_Models, state schema, config, project structure._

**Deliverables:**
- [x] `action_agent/models/schemas.py` — all Pydantic models
- [x] `action_agent/models/state.py` — LangGraph `MeetingDebriefState` TypedDict
- [x] `action_agent/config.py` — `Settings` (pydantic-settings, no MCP flags)
- [x] `pyproject.toml`, `requirements.txt`
- [x] `tests/test_phase1_skeleton.py` — 21 tests green

---

### Phase 2 — Agent Pipeline [COMPLETE ✅]
_LLM-powered agents: summarize, extract, assign, validate._

**Deliverables:**
- [x] `action_agent/agents/summarizer.py`
- [x] `action_agent/agents/action_extractor.py`
- [x] `action_agent/agents/assignment.py`
- [x] `action_agent/agents/validator.py`
- [x] `action_agent/graph/` — nodes, conditions, builder
- [x] `tests/test_phase2_llm.py` — 13 tests green

---

### Phase 3 — Dispatch Layer (Direct SDK) [IN PROGRESS 🔄]
_Replace MCP stubs with direct API SDK calls. Dry-run when credentials absent._

**Deliverables:**
- [ ] Remove `action_agent/mcp/` directory entirely
- [ ] `action_agent/graph/nodes.py` — dispatch nodes using notion-client, jira, slack-sdk
- [ ] Dry-run mode: `DispatchResult(success=True, item_id="dry-run-<id>")` when credentials blank
- [ ] `tests/test_phase3_dispatch.py` — tests covering both dry-run and full graph

**Test gate:** All Phase 3 tests GREEN before commit.

---

### Phase 4 — CLI [COMPLETE ✅]
_Typer CLI entry point with Rich output._

**Deliverables:**
- [x] `main.py` — `python main.py <transcript.txt> [--team "..."]`
- [x] Rich table output for action items and dispatch results

---

### Phase 5 — REST API & Web UI [COMPLETE ✅]
_FastAPI server with sync endpoint, SSE streaming, and HTML frontend._

**Deliverables:**
- [x] `api.py` — `/health`, `/debrief`, `/debrief/jobs`, `/debrief/jobs/{id}/stream`
- [x] `frontend/index.html` — SSE-driven SPA
- [x] `tests/test_phase5_api.py` — 10 tests green

---

### Phase 6 — Live Integration & Hardening [COMPLETE ✅]
_Wire real credentials; add retry logic, structured logging, run history._

**Deliverables:**
- [x] Integration tests for Notion, Jira, Slack (auto-skip when credentials absent)
- [x] Retry with exponential backoff (3 attempts) on dispatch SDK errors
- [x] Structured JSON logging (`action_agent/utils/logging.py`) — `get_logger`, `log_node_event`
- [x] `AsyncSqliteSaver` checkpointer for persistent run history
- [x] `GET /runs/{thread_id}` endpoint to retrieve prior run state
- [x] `POST /debrief` accepts optional `thread_id` for named runs
- [x] `tests/test_phase6_hardening.py` — 26 passed, 3 skipped (live creds required)

---

## 8. Development Rules

1. **Constitution first.** When adding a feature, update this document before writing code.
2. **Tests before code.** Testing agent generates tests for each phase; implementation follows.
3. **No MCP.** Dispatch nodes use SDK clients directly. MCP protocol is not part of this system.
4. **Dry-run is not an error.** Missing credentials produce synthetic success results, not startup failures.
5. **No silent drops.** Every action item is dispatched, even `needs_clarification=True` ones (tagged).
6. **Green gate.** Nothing is committed until all non-skipped tests pass.
