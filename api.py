"""
FastAPI server — serves the web UI and the /debrief REST endpoint.

Phase 1: /health + stub /debrief endpoint.
Phase 5: full implementation + SSE streaming + static frontend.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path

app = FastAPI(title="Meeting Debrief Agent", version="0.1.0")

FRONTEND_DIR = Path(__file__).parent / "frontend"


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── Debrief endpoint ──────────────────────────────────────────────────────────

class TranscriptRequest(BaseModel):
    transcript: str
    team_members: list[str] = []


class DebriefResponse(BaseModel):
    status: str
    summary: dict | None = None
    action_items: list[dict] = []
    dispatch_results: list[dict] = []


@app.post("/debrief", response_model=DebriefResponse)
async def debrief(request: TranscriptRequest):
    from action_agent.config import settings
    from action_agent.graph.builder import build_graph

    from action_agent.mcp.client import get_mcp_tools

    graph = build_graph()
    initial_state = {
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

    async with get_mcp_tools() as mcp_tools:
        config = {"configurable": {"thread_id": "api-run", "mcp_tools": mcp_tools}}
        final_updates: dict = {}
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            for updates in event.values():
                if isinstance(updates, dict):
                    final_updates.update(updates)

    merged = {**initial_state, **final_updates}

    vr = merged.get("validation_result")
    items = (vr.valid_items + vr.flagged_items) if vr else []

    return DebriefResponse(
        status=merged.get("status", "complete"),
        summary=merged["summary"].model_dump() if merged.get("summary") else None,
        action_items=[i.model_dump() for i in items],
        dispatch_results=[r.model_dump() for r in merged.get("dispatch_results", [])],
    )


# ── Frontend (Phase 5) ────────────────────────────────────────────────────────

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(FRONTEND_DIR / "index.html")
