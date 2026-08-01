"""
db.py
Lightweight SQLite persistence layer for tracking remediation tasks.

Each row represents one "remediation task": one GitHub issue that was
sent to Devin to be fixed. We track its lifecycle from creation ->
in_progress -> completed/failed, plus timing info for throughput metrics.
"""

import os
import sqlite3
import time
from contextlib import contextmanager

DB_DIR = os.getenv("DB_DIR", "data")
DB_PATH = os.path.join(DB_DIR, "remediation.db")
os.makedirs(DB_DIR, exist_ok=True)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_url TEXT NOT NULL,
                issue_number INTEGER,
                issue_title TEXT,
                devin_session_id TEXT,
                devin_session_url TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                pr_url TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                error_message TEXT
            )
            """
        )


def create_task(issue_url: str, issue_number: int, issue_title: str) -> int:
    now = time.time()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks (issue_url, issue_number, issue_title, status, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', ?, ?)
            """,
            (issue_url, issue_number, issue_title, now, now),
        )
        return cur.lastrowid


def set_devin_session(task_id: int, session_id: str, session_url: str):
    now = time.time()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET devin_session_id = ?, devin_session_url = ?, status = 'in_progress', updated_at = ?
            WHERE id = ?
            """,
            (session_id, session_url, now, task_id),
        )


def update_status(task_id: int, status: str, pr_url: str | None = None, error_message: str | None = None):
    now = time.time()
    completed_at = now if status in ("completed", "failed") else None
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = ?, pr_url = COALESCE(?, pr_url), error_message = ?,
                updated_at = ?, completed_at = COALESCE(?, completed_at)
            WHERE id = ?
            """,
            (status, pr_url, error_message, now, completed_at, task_id),
        )


def get_task(task_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def get_all_tasks():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_stats():
    tasks = get_all_tasks()
    total = len(tasks)
    completed = [t for t in tasks if t["status"] == "completed"]
    failed = [t for t in tasks if t["status"] == "failed"]
    in_progress = [t for t in tasks if t["status"] == "in_progress"]
    queued = [t for t in tasks if t["status"] == "queued"]

    durations = [
        t["completed_at"] - t["created_at"]
        for t in completed
        if t["completed_at"]
    ]
    avg_duration_min = (sum(durations) / len(durations) / 60) if durations else 0
    success_rate = (len(completed) / total * 100) if total else 0

    return {
        "total": total,
        "completed": len(completed),
        "failed": len(failed),
        "in_progress": len(in_progress),
        "queued": len(queued),
        "success_rate": round(success_rate, 1),
        "avg_duration_min": round(avg_duration_min, 1),
    }
