"""
Phase 5 tests — FastAPI server, SSE streaming, and web UI.
"""
import json
import httpx
import pytest

SHORT_TRANSCRIPT = """
Meeting: Bug Fix Standup
Participants: Alice Smith, Bob Jones, Carol White

Alice Smith: We need to fix the login bug urgently. Bob, can you take that by Thursday?
Bob Jones: Yes, I'll have the login bug fix done by May 7th.
Alice Smith: Great. Carol, please update the API docs by end of next week.
Carol White: Sure, I'll have the API documentation updated by May 10th.
Alice Smith: One more - Bob can you also review the PR for the caching layer by May 8th?
Bob Jones: No problem.
"""


def _client():
    from api import app
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


# ── Health ────────────────────────────────────────────────────────────────────

async def test_health_returns_ok():
    async with _client() as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Frontend ──────────────────────────────────────────────────────────────────

async def test_root_serves_html():
    async with _client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Meeting Debrief" in resp.text


async def test_root_contains_transcript_input():
    async with _client() as client:
        resp = await client.get("/")
    assert "transcript" in resp.text.lower()


# ── POST /debrief (sync endpoint) ────────────────────────────────────────────

async def test_debrief_post_returns_complete():
    async with _client() as client:
        resp = await client.post(
            "/debrief",
            json={"transcript": SHORT_TRANSCRIPT, "team_members": ["Alice Smith", "Bob Jones", "Carol White"]},
            timeout=120,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "complete"
    assert isinstance(body["action_items"], list)
    assert len(body["action_items"]) > 0


async def test_debrief_post_summary_populated():
    async with _client() as client:
        resp = await client.post(
            "/debrief",
            json={"transcript": SHORT_TRANSCRIPT, "team_members": ["Alice Smith", "Bob Jones", "Carol White"]},
            timeout=120,
        )
    body = resp.json()
    assert body["summary"] is not None
    assert body["summary"]["title"]


async def test_debrief_post_dispatch_results():
    async with _client() as client:
        resp = await client.post(
            "/debrief",
            json={"transcript": SHORT_TRANSCRIPT, "team_members": ["Alice Smith", "Bob Jones", "Carol White"]},
            timeout=120,
        )
    body = resp.json()
    tool_names = {r["tool"] for r in body["dispatch_results"]}
    assert "notion" in tool_names
    assert "jira" in tool_names
    assert "slack" in tool_names


# ── POST /debrief/jobs + GET /debrief/jobs/{id}/stream ────────────────────────

async def test_create_job_returns_job_id():
    async with _client() as client:
        resp = await client.post(
            "/debrief/jobs",
            json={"transcript": SHORT_TRANSCRIPT, "team_members": ["Alice Smith"]},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert len(body["job_id"]) > 0


async def test_stream_unknown_job_returns_404():
    async with _client() as client:
        resp = await client.get("/debrief/jobs/nonexistent-id/stream")
    assert resp.status_code == 404


async def test_stream_sends_progress_and_complete_events():
    """Full SSE flow: create job → stream → parse events → verify complete."""
    async with _client() as client:
        # Create job
        job_resp = await client.post(
            "/debrief/jobs",
            json={"transcript": SHORT_TRANSCRIPT, "team_members": ["Alice Smith", "Bob Jones", "Carol White"]},
        )
        assert job_resp.status_code == 200
        job_id = job_resp.json()["job_id"]

        # Stream and collect events
        events: list[dict] = []
        async with client.stream(
            "GET", f"/debrief/jobs/{job_id}/stream", timeout=120
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

            current_event_type = None
            async for line in resp.aiter_lines():
                line = line.strip()
                if line.startswith("event:"):
                    current_event_type = line[6:].strip()
                elif line.startswith("data:") and current_event_type:
                    data = json.loads(line[5:].strip())
                    events.append({"type": current_event_type, "data": data})
                    if current_event_type == "complete":
                        break

    event_types = {e["type"] for e in events}
    assert "progress" in event_types, "Expected progress events from pipeline nodes"
    assert "complete" in event_types, "Expected a final complete event"

    complete = next(e for e in events if e["type"] == "complete")
    assert complete["data"]["status"] == "complete"
    assert len(complete["data"]["action_items"]) > 0


async def test_stream_complete_has_all_dispatch_tools():
    async with _client() as client:
        job_resp = await client.post(
            "/debrief/jobs",
            json={"transcript": SHORT_TRANSCRIPT, "team_members": ["Alice Smith", "Bob Jones", "Carol White"]},
        )
        job_id = job_resp.json()["job_id"]

        complete_data = None
        async with client.stream("GET", f"/debrief/jobs/{job_id}/stream", timeout=120) as resp:
            current_event_type = None
            async for line in resp.aiter_lines():
                line = line.strip()
                if line.startswith("event:"):
                    current_event_type = line[6:].strip()
                elif line.startswith("data:") and current_event_type == "complete":
                    complete_data = json.loads(line[5:].strip())
                    break

    assert complete_data is not None
    tool_names = {r["tool"] for r in complete_data["dispatch_results"]}
    assert {"notion", "jira", "slack"} == tool_names
