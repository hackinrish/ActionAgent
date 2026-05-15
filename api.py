"""
FastAPI server — serves the web UI and all API endpoints.

Endpoints:
  GET  /                          → serve frontend/index.html
  GET  /health                    → {"status": "ok"}
  POST /debrief                   → synchronous full pipeline result
  POST /debrief/jobs              → create streaming job, returns {"job_id": "..."}
  GET  /debrief/jobs/{id}/stream  → SSE stream of pipeline progress + final result
  GET  /runs/{thread_id}          → retrieve prior run by thread_id
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Meeting Debrief Agent", version="0.1.0")

FRONTEND_DIR = Path(__file__).parent / "frontend"
_RUNS_DB = str(Path(__file__).parent / ".actionagent_runs.db")

# In-memory job queue: job_id → TranscriptRequest
_pending_jobs: dict[str, "TranscriptRequest"] = {}


def _get_checkpointer():
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    return AsyncSqliteSaver.from_conn_string(_RUNS_DB)


# ── Models ────────────────────────────────────────────────────────────────────

class TranscriptRequest(BaseModel):
    transcript: str
    team_members: list[str] = []
    thread_id: Optional[str] = None


class DebriefResponse(BaseModel):
    status: str
    summary: dict | None = None
    action_items: list[dict] = []
    dispatch_results: list[dict] = []


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


def _checkpoint_to_response(checkpoint: dict) -> DebriefResponse:
    """Build a DebriefResponse from a LangGraph checkpoint's channel_values."""
    cv = checkpoint.get("channel_values", {})
    status = cv.get("status", "complete")

    vr = cv.get("validation_result")
    if vr:
        items = vr.valid_items + vr.flagged_items
    else:
        items = []

    summary_obj = cv.get("summary")
    return DebriefResponse(
        status=status,
        summary=summary_obj.model_dump() if summary_obj else None,
        action_items=[i.model_dump() for i in items],
        dispatch_results=[r.model_dump() for r in cv.get("dispatch_results", [])],
    )


# ── POST /debrief — synchronous ───────────────────────────────────────────────

@app.post("/debrief", response_model=DebriefResponse)
async def debrief(request: TranscriptRequest):
    from action_agent.graph.builder import build_graph

    thread_id = request.thread_id or f"api-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = _build_initial_state(request)
    final_updates: dict = {}

    async with _get_checkpointer() as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
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

        def sse(event_type: str, data: dict) -> str:
            return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

        thread_id = request.thread_id or f"sse-{job_id}"
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = _build_initial_state(request)
        final_updates: dict = {}

        try:
            async with _get_checkpointer() as checkpointer:
                graph = build_graph(checkpointer=checkpointer)
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


# ── GET /runs/{thread_id} — retrieve prior run ────────────────────────────────

@app.get("/runs/{thread_id}", response_model=DebriefResponse)
async def get_run(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    async with _get_checkpointer() as checkpointer:
        checkpoint = await checkpointer.aget(config)
    if checkpoint is None:
        raise HTTPException(status_code=404, detail=f"No run found for thread_id '{thread_id}'")
    return _checkpoint_to_response(checkpoint)


# ── Frontend static files ─────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return {"message": "Frontend not built yet — run the app with Phase 5 complete"}
    return FileResponse(index)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
