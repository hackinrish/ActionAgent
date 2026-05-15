# ActionAgent — Constitution

_This document is the authoritative source of truth for the ActionAgent system.
All implementation decisions, test cases, and architectural choices are derived from it.
When code and Constitution conflict, the Constitution wins — fix the code._

---

## 1. Mission Statement

ActionAgent transforms unstructured meeting transcripts into structured, dispatched work.
It ingests a raw transcript, runs a multi-agent LangGraph pipeline to extract and assign
action items, validates them, and persists everything locally — tasks to a Database view,
meeting history to a Meetings view, and a broadcast to the Channel feed.

**Success criterion:** Given a meeting transcript and a list of team members, the system
produces fully assigned, deadline-bearing action items and stores them in the local SQLite
database within one pipeline run, requiring no human intervention and no external API keys.

---

## 2. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| LLM | Anthropic Claude (claude-sonnet-4-6) | Best-in-class instruction following for structured extraction |
| Agent orchestration | LangGraph 0.5+ (StateGraph) | Native graph pipeline, built-in checkpointing |
| LLM client | langchain-anthropic + langchain-core | `with_structured_output` for schema-enforced extraction |
| Data validation | Pydantic v2 | Runtime schema enforcement, IDE-friendly |
| Config | pydantic-settings | `.env` + env var loading, typed settings |
| Local storage | aiosqlite | Async SQLite — meetings, tasks, channel_messages tables |
| REST API | FastAPI | Async, SSE streaming, auto-docs |
| Web UI | Vanilla HTML/JS | No build step, SSE-native via EventSource, 4-tab SPA |
| CLI | Typer + Rich | Clean UX, no boilerplate |
| Testing | pytest + pytest-asyncio (asyncio_mode=auto) | Async-first, fixtures |

**Not used:** MCP protocol, external service SDKs (Notion, Jira, Slack).
All dispatch writes directly to local SQLite via `action_agent/db.py`.

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
tool: str          # "local"
success: bool
item_id: str | None   # meeting UUID from local DB
error_message: str | None
```

### Local DB Schema (SQLite, `local.db`)

**meetings**
```
id: TEXT PK (uuid)
thread_id: TEXT UNIQUE
title, date, summary, participants (JSON), key_decisions (JSON): TEXT
created_at: TEXT (ISO timestamp)
```

**tasks**
```
id: TEXT PK (uuid)
meeting_id: TEXT FK → meetings.id
description, owner, deadline, priority: TEXT
status: TEXT DEFAULT 'todo'   # todo | in_progress | done
needs_clarification: INTEGER (0/1)
clarification_reason: TEXT
created_at, updated_at: TEXT
```

**channel_messages**
```
id: TEXT PK (uuid)
meeting_id: TEXT FK → meetings.id
content: TEXT
created_at: TEXT
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
                          └─[valid OR max attempts reached]─► dispatch_local ─► aggregate_dispatch ─► END
```

### Node contracts

| Node | Reads from state | Writes to state |
|---|---|---|
| `summarize` | `transcript` | `summary` |
| `extract_actions` | `transcript`, `summary`, `validation_result.flagged_items?` | `raw_action_items` |
| `assign_owners` | `raw_action_items`, `team_members`, `transcript` | `assigned_action_items` |
| `validate` | `assigned_action_items`, `validation_attempts` | `validation_result`, `validation_attempts` |
| `dispatch_local` | `validation_result`, `summary`, config thread_id | `dispatch_results` |
| `aggregate_dispatch` | `dispatch_results` | `status`, `dispatch_results` |

### Dispatch behavior contract
- `dispatch_local_node` always writes to SQLite — no credentials required
- Creates/upserts meeting row, inserts tasks, inserts channel message
- Returns `DispatchResult(tool="local", success=True, item_id=<meeting_uuid>)`
- On DB error: returns `DispatchResult(tool="local", success=False, error_message=<exc>)`
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

### `GET /tasks`
Query params: `meeting_id`, `status`, `owner` (all optional)
Response: `list[dict]` — task rows from DB

### `PATCH /tasks/{id}`
Body: `{ "status"?: str, "owner"?: str, "deadline"?: str }`
Response: updated task row

### `GET /meetings`
Response: `list[dict]` — meeting rows, newest first

### `GET /meetings/{id}`
Response: meeting row + `"tasks": list[dict]`

### `GET /channel`
Response: `list[dict]` — channel messages, newest first

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
| `LOCAL_DB_PATH` | str | Default: `local.db` |
| `MAX_VALIDATION_ATTEMPTS` | int | Default: `3` |

No external service credentials needed. Everything runs locally.

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

### Phase 2 — Agent Pipeline [COMPLETE ✅]
_LLM-powered agents: summarize, extract, assign, validate._

### Phase 3 — Dispatch Layer (Direct SDK) [COMPLETE ✅]
_Replaced with local SQLite dispatch. No external services._

### Phase 4 — CLI [COMPLETE ✅]
_Typer CLI entry point with Rich output._

### Phase 5 — REST API & Web UI [COMPLETE ✅]
_FastAPI server with sync endpoint, SSE streaming, and HTML frontend._

### Phase 6 — Hardening [COMPLETE ✅]
_Structured JSON logging. Retry removed (no external calls to retry)._

### Phase 7 — Local-First Revamp [COMPLETE ✅]
_Removed Notion, Jira, Slack. Replaced with in-app equivalents stored in SQLite._

**Deliverables:**
- [x] `action_agent/db.py` — SQLite schema + async CRUD helpers
- [x] `dispatch_local_node` in `nodes.py` — single dispatch, writes meeting/tasks/channel
- [x] Simplified graph (no parallel fan-out; linear → `dispatch_local`)
- [x] Removed external service keys from `config.py` and `requirements.txt`
- [x] New API endpoints: `GET /tasks`, `PATCH /tasks/{id}`, `GET /meetings`, `GET /meetings/{id}`, `GET /channel`
- [x] Removed `GET /runs/{thread_id}`
- [x] Rebuilt `frontend/index.html` — 4-tab SPA: Run, Board, Database, Channel
- [x] `tests/test_phase7_local.py` — 29 tests green

---

## 8. Development Rules

1. **Constitution first.** When adding a feature, update this document before writing code.
2. **Tests before code.** Testing agent generates tests for each phase; implementation follows.
3. **No external services.** All dispatch uses local SQLite. No API keys for dispatch.
4. **Dry-run is not needed.** There is no external call — local write always works.
5. **No silent drops.** Every action item is dispatched, even `needs_clarification=True` ones (tagged).
6. **Green gate.** Nothing is committed until all non-skipped tests pass.
