"""
FastAPI server — serves the web UI and all API endpoints.

Endpoints:
  GET  /                           → serve frontend/index.html
  GET  /health                     → {"status": "ok"}
  POST /debrief                    → synchronous full pipeline result
  POST /debrief/jobs               → create streaming job, returns {"job_id": "..."}
  GET  /debrief/jobs/{id}/stream   → SSE stream of pipeline progress + final result
  GET  /tasks                      → list tasks (optional ?meeting_id=, ?status=, ?owner=)
  PATCH /tasks/{id}                → update task status/owner/deadline
  GET  /meetings                   → list all meeting summaries
  GET  /meetings/{id}              → single meeting + its tasks
  GET  /channel                    → channel messages newest first
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Meeting Debrief Agent", version="0.1.0")

FRONTEND_DIR = Path(__file__).parent / "frontend"


def _db_path() -> str:
    from action_agent.config import settings
    return settings.local_db_path


# In-memory job queue: job_id → TranscriptRequest
_pending_jobs: dict[str, "TranscriptRequest"] = {}


# ── Models ────────────────────────────────────────────────────────────────────

class TranscriptRequest(BaseModel):
    transcript: str
    team_members: list[str] = []


class DebriefResponse(BaseModel):
    status: str
    summary: dict | None = None
    action_items: list[dict] = []
    dispatch_results: list[dict] = []


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    owner: Optional[str] = None
    deadline: Optional[str] = None


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_initial_state(request: TranscriptRequest) -> dict:
    from action_agent.config import settings
    return {
        "transcript": request.transcript,
        "team_members": request.team_members or settings.team_members,
        "messages": [],
        "summary": None,
        "raw_action_items": [],
        "assigned_action_items": [],
        "validation_result": None,
        "validation_attempts": 0,
        "dispatch_results": [],
        "error": None,
        "status": "running",
    }


def _merged_to_response(merged: dict) -> DebriefResponse:
    vr = merged.get("validation_result")
    items = (vr.valid_items + vr.flagged_items) if vr else []
    return DebriefResponse(
        status=merged.get("status", "complete"),
        summary=merged["summary"].model_dump() if merged.get("summary") else None,
        action_items=[i.model_dump() for i in items],
        dispatch_results=[r.model_dump() for r in merged.get("dispatch_results", [])],
    )


# ── POST /debrief — synchronous ───────────────────────────────────────────────

@app.post("/debrief", response_model=DebriefResponse)
async def debrief(request: TranscriptRequest):
    from action_agent.graph.builder import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    thread_id = f"api-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = _build_initial_state(request)
    final_updates: dict = {}

    graph = build_graph(checkpointer=MemorySaver())
    async for event in graph.astream(initial_state, config, stream_mode="updates"):
        for updates in event.values():
            if isinstance(updates, dict):
                final_updates.update(updates)

    merged = {**initial_state, **final_updates}
    return _merged_to_response(merged)


# ── POST /debrief/jobs — create streaming job ─────────────────────────────────

@app.post("/debrief/jobs")
async def create_job(request: TranscriptRequest) -> dict:
    job_id = uuid.uuid4().hex[:12]
    _pending_jobs[job_id] = request
    return {"job_id": job_id}


# ── GET /debrief/jobs/{job_id}/stream — SSE stream ───────────────────────────

@app.get("/debrief/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    request = _pending_jobs.pop(job_id, None)
    if request is None:
        raise HTTPException(status_code=404, detail="Job not found or already consumed")

    async def generate() -> AsyncIterator[str]:
        from action_agent.graph.builder import build_graph
        from langgraph.checkpoint.memory import MemorySaver

        def sse(event_type: str, data: dict) -> str:
            return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

        thread_id = f"sse-{job_id}"
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = _build_initial_state(request)
        final_updates: dict = {}

        try:
            graph = build_graph(checkpointer=MemorySaver())
            async for event in graph.astream(initial_state, config, stream_mode="updates"):
                for node_name, updates in event.items():
                    yield sse("progress", {"node": node_name, "status": "complete"})
                    if isinstance(updates, dict):
                        final_updates.update(updates)

            merged = {**initial_state, **final_updates}
            response = _merged_to_response(merged)
            yield sse("complete", {"type": "complete", **response.model_dump()})

        except Exception as exc:
            yield sse("error", {"type": "error", "message": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── GET /tasks ────────────────────────────────────────────────────────────────

@app.get("/tasks")
async def list_tasks(
    meeting_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    owner: Optional[str] = Query(None),
):
    from action_agent.db import get_tasks
    return await get_tasks(_db_path(), meeting_id=meeting_id, status=status, owner=owner)


# ── PATCH /tasks/{task_id} ────────────────────────────────────────────────────

@app.patch("/tasks/{task_id}")
async def patch_task(task_id: str, body: TaskUpdate):
    from action_agent.db import update_task, get_task
    found = await update_task(
        _db_path(),
        task_id=task_id,
        status=body.status,
        owner=body.owner,
        deadline=body.deadline,
    )
    if not found:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return await get_task(_db_path(), task_id=task_id)


# ── GET /meetings ─────────────────────────────────────────────────────────────

@app.get("/meetings")
async def list_meetings():
    from action_agent.db import get_meetings
    return await get_meetings(_db_path())


# ── GET /meetings/{meeting_id} ────────────────────────────────────────────────

@app.get("/meetings/{meeting_id}")
async def get_meeting_detail(meeting_id: str):
    from action_agent.db import get_meeting, get_tasks
    meeting = await get_meeting(_db_path(), meeting_id=meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail=f"Meeting '{meeting_id}' not found")
    tasks = await get_tasks(_db_path(), meeting_id=meeting_id)
    return {**meeting, "tasks": tasks}


# ── GET /channel ──────────────────────────────────────────────────────────────

@app.get("/channel")
async def list_channel():
    from action_agent.db import get_channel
    return await get_channel(_db_path())


# ── Frontend static files ─────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return {"message": "Frontend not built yet"}
    return FileResponse(index)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
