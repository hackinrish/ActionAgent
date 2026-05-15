"""
Local SQLite database layer.

Tables:
  meetings        — one row per pipeline run
  tasks           — one row per action item
  channel_messages — one message per meeting run (Slack-like feed)
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import aiosqlite

_DEFAULT_DB = "local.db"


@asynccontextmanager
async def get_connection(db_path: str = _DEFAULT_DB):
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn


async def init_db(db_path: str = _DEFAULT_DB) -> None:
    async with get_connection(db_path) as conn:
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS meetings (
                id          TEXT PRIMARY KEY,
                thread_id   TEXT UNIQUE,
                title       TEXT,
                date        TEXT,
                summary     TEXT,
                participants TEXT,
                key_decisions TEXT,
                created_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id                   TEXT PRIMARY KEY,
                meeting_id           TEXT REFERENCES meetings(id),
                description          TEXT,
                owner                TEXT,
                deadline             TEXT,
                priority             TEXT,
                status               TEXT DEFAULT 'todo',
                needs_clarification  INTEGER DEFAULT 0,
                clarification_reason TEXT,
                created_at           TEXT,
                updated_at           TEXT
            );

            CREATE TABLE IF NOT EXISTS channel_messages (
                id          TEXT PRIMARY KEY,
                meeting_id  TEXT REFERENCES meetings(id),
                content     TEXT,
                created_at  TEXT
            );
        """)
        await conn.commit()


async def save_meeting(
    db_path: str,
    *,
    thread_id: str,
    summary,
) -> str:
    """Upsert a meeting row; return the meeting id."""
    await init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()

    async with get_connection(db_path) as conn:
        # Check if thread_id already exists
        cursor = await conn.execute(
            "SELECT id FROM meetings WHERE thread_id = ?", (thread_id,)
        )
        row = await cursor.fetchone()
        if row:
            meeting_id = row[0]
            await conn.execute(
                """UPDATE meetings
                   SET title=?, date=?, summary=?, participants=?, key_decisions=?
                   WHERE id=?""",
                (
                    summary.title,
                    summary.date,
                    summary.summary,
                    json.dumps(summary.participants),
                    json.dumps(summary.key_decisions),
                    meeting_id,
                ),
            )
        else:
            meeting_id = str(uuid.uuid4())
            await conn.execute(
                """INSERT INTO meetings (id, thread_id, title, date, summary, participants, key_decisions, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meeting_id,
                    thread_id,
                    summary.title,
                    summary.date,
                    summary.summary,
                    json.dumps(summary.participants),
                    json.dumps(summary.key_decisions),
                    now,
                ),
            )
        await conn.commit()
    return meeting_id


async def save_tasks(db_path: str, *, meeting_id: str, validation_result) -> None:
    """Insert all action items from a ValidationResult into the tasks table."""
    await init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    all_items = validation_result.valid_items + validation_result.flagged_items

    async with get_connection(db_path) as conn:
        for item in all_items:
            task_id = str(uuid.uuid4())
            await conn.execute(
                """INSERT INTO tasks
                   (id, meeting_id, description, owner, deadline, priority, status,
                    needs_clarification, clarification_reason, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'todo', ?, ?, ?, ?)""",
                (
                    task_id,
                    meeting_id,
                    item.description,
                    item.owner,
                    item.deadline,
                    item.priority.value,
                    1 if item.needs_clarification else 0,
                    item.clarification_reason,
                    now,
                    now,
                ),
            )
        await conn.commit()


async def save_channel_message(db_path: str, *, meeting_id: str, content: str) -> str:
    """Insert a channel message; return its id."""
    now = datetime.now(timezone.utc).isoformat()
    msg_id = str(uuid.uuid4())
    await init_db(db_path)
    async with get_connection(db_path) as conn:
        await conn.execute(
            "INSERT INTO channel_messages (id, meeting_id, content, created_at) VALUES (?, ?, ?, ?)",
            (msg_id, meeting_id, content, now),
        )
        await conn.commit()
    return msg_id


async def get_tasks(
    db_path: str = _DEFAULT_DB,
    *,
    meeting_id: str | None = None,
    status: str | None = None,
    owner: str | None = None,
) -> list[dict[str, Any]]:
    """Return tasks matching optional filters, as plain dicts."""
    clauses = []
    params: list[Any] = []
    if meeting_id:
        clauses.append("meeting_id = ?")
        params.append(meeting_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if owner:
        clauses.append("owner = ?")
        params.append(owner)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    query = f"SELECT * FROM tasks {where} ORDER BY created_at ASC"

    await init_db(db_path)
    async with get_connection(db_path) as conn:
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_task(db_path: str = _DEFAULT_DB, *, task_id: str) -> dict[str, Any] | None:
    """Return a single task dict or None."""
    await init_db(db_path)
    async with get_connection(db_path) as conn:
        cursor = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
    return dict(row) if row else None


async def update_task(
    db_path: str = _DEFAULT_DB,
    *,
    task_id: str,
    status: str | None = None,
    owner: str | None = None,
    deadline: str | None = None,
) -> bool:
    """Update mutable fields of a task. Returns True if row was found."""
    now = datetime.now(timezone.utc).isoformat()
    sets = ["updated_at = ?"]
    params: list[Any] = [now]
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if owner is not None:
        sets.append("owner = ?")
        params.append(owner)
    if deadline is not None:
        sets.append("deadline = ?")
        params.append(deadline)
    params.append(task_id)

    await init_db(db_path)
    async with get_connection(db_path) as conn:
        cursor = await conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params
        )
        await conn.commit()
        return cursor.rowcount > 0


async def get_meetings(db_path: str = _DEFAULT_DB) -> list[dict[str, Any]]:
    """Return all meetings newest first."""
    await init_db(db_path)
    async with get_connection(db_path) as conn:
        cursor = await conn.execute(
            "SELECT * FROM meetings ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_meeting(db_path: str = _DEFAULT_DB, *, meeting_id: str) -> dict[str, Any] | None:
    """Return a single meeting dict or None."""
    await init_db(db_path)
    async with get_connection(db_path) as conn:
        cursor = await conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,))
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_channel(db_path: str = _DEFAULT_DB) -> list[dict[str, Any]]:
    """Return channel messages newest first."""
    await init_db(db_path)
    async with get_connection(db_path) as conn:
        cursor = await conn.execute(
            "SELECT * FROM channel_messages ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]
