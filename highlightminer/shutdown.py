from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .storage import connect

_SHUTDOWN_ADMISSION_KEY = "ui_shutdown_admission"
_SHUTDOWN_ADMISSION_TTL = timedelta(seconds=60)


class ShutdownInProgressError(RuntimeError):
    """Raised when new work loses the race against an accepted app shutdown."""


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fresh_shutdown_admission(
    conn: sqlite3.Connection,
    *,
    now: datetime,
) -> bool:
    row = conn.execute(
        "SELECT value FROM metadata WHERE key = ?",
        (_SHUTDOWN_ADMISSION_KEY,),
    ).fetchone()
    if row is None:
        return False

    requested_at = _parse_timestamp(str(row["value"]))
    if requested_at is not None and abs(now - requested_at) <= _SHUTDOWN_ADMISSION_TTL:
        return True

    conn.execute("DELETE FROM metadata WHERE key = ?", (_SHUTDOWN_ADMISSION_KEY,))
    return False


def _active_work_shutdown_block_reason(conn: sqlite3.Connection) -> str | None:
    analysis_job = conn.execute(
        """
        SELECT status FROM analysis_jobs
        WHERE status IN ('queued', 'running')
        ORDER BY created_at LIMIT 1
        """
    ).fetchone()
    if analysis_job is not None:
        return (
            "Analysis is still starting or running. HighlightMiner cannot safely cancel "
            "this stage, so wait for it to finish or reach the model choice before exiting."
        )

    export_batch = conn.execute(
        "SELECT 1 FROM export_batches WHERE status = 'running' LIMIT 1"
    ).fetchone()
    if export_batch is not None:
        return (
            "An export batch is still running. HighlightMiner cannot safely cancel FFmpeg "
            "mid-export, so wait for the batch to finish before exiting."
        )

    return None


def active_work_shutdown_block_reason(db_path: str | Path) -> str | None:
    """Read the current reason used to disable the in-app Exit control."""
    with connect(db_path) as conn:
        return _active_work_shutdown_block_reason(conn)


def request_shutdown_admission(
    db_path: str | Path,
    *,
    now: datetime | None = None,
) -> str | None:
    """Atomically reserve shutdown, or return the active work that blocks it."""
    requested_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if _fresh_shutdown_admission(conn, now=requested_at):
            conn.commit()
            return None

        block_reason = _active_work_shutdown_block_reason(conn)
        if block_reason:
            conn.commit()
            return block_reason

        conn.execute(
            """
            INSERT INTO metadata(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (_SHUTDOWN_ADMISSION_KEY, requested_at.isoformat(timespec="seconds")),
        )
        conn.commit()
    return None


def ensure_work_admitted(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
) -> None:
    """Reject new work after shutdown has won the shared SQLite admission lock."""
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if _fresh_shutdown_admission(conn, now=observed_at):
        raise ShutdownInProgressError(
            "HighlightMiner is shutting down, so new analysis/export work cannot start."
        )


def clear_shutdown_admission(db_path: str | Path) -> None:
    """Clear this launch's short-lived shutdown reservation."""
    with connect(db_path) as conn:
        conn.execute("DELETE FROM metadata WHERE key = ?", (_SHUTDOWN_ADMISSION_KEY,))
        conn.commit()
