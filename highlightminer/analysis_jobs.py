from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .storage import connect, utc_now

ACTIVE_ANALYSIS_JOB_STATUSES = ("queued", "running", "awaiting_input")
TERMINAL_ANALYSIS_JOB_STATUSES = ("completed", "failed", "cancelled", "interrupted")
ANALYSIS_JOB_HEARTBEAT_INTERVAL_SECONDS = 10.0
ANALYSIS_JOB_STALE_AFTER_SECONDS = 90.0
_EVENT_LEVELS = {"info", "warning", "error"}


class AnalysisJobStateError(RuntimeError):
    """The requested analysis-job transition is not valid from its current state."""


class ActiveAnalysisJobError(AnalysisJobStateError):
    """A source already has an active analysis job."""

    def __init__(self, job: dict[str, Any]):
        self.job = job
        super().__init__(
            f"Analysis job {job['id']} is already {str(job['status']).replace('_', ' ')} "
            "for this source."
        )


class AnalysisJobTerminalError(AnalysisJobStateError):
    """A concurrent transition ended a job before the current worker could continue."""

    def __init__(self, job: dict[str, Any]):
        self.job = dict(job)
        super().__init__(
            f"Analysis job {job['id']} reached terminal state {job['status']}."
        )


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decode(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _merge_timings(value: str | None, updates: dict[str, float] | None) -> dict[str, float]:
    merged = {str(key): float(item) for key, item in dict(_decode(value, {})).items()}
    for name, item in (updates or {}).items():
        numeric = float(item)
        if numeric < 0.0:
            raise ValueError(f"Analysis timing {name!r} cannot be negative.")
        merged[str(name)] = numeric
    return merged


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "source_id": str(row["source_id"]),
        "source_fingerprint": str(row["source_fingerprint"]),
        "status": str(row["status"]),
        "stage": str(row["stage"]),
        "progress": float(row["progress"]),
        "message": str(row["message"]),
        "config": _decode(row["config_json"], {}),
        "timings": _decode(row["timings_json"], {}),
        "analysis_id": row["analysis_id"],
        "error_type": row["error_type"],
        "error_message": row["error_message"],
        "created_at": str(row["created_at"]),
        "started_at": row["started_at"],
        "updated_at": str(row["updated_at"]),
        "finished_at": row["finished_at"],
    }


def _event(
    conn: sqlite3.Connection,
    job_id: str,
    event: str,
    *,
    level: str = "info",
    stage: str | None = None,
    message: str = "",
    details: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> None:
    if level not in _EVENT_LEVELS:
        raise ValueError(f"Unsupported analysis-job event level: {level}")
    conn.execute(
        """
        INSERT INTO analysis_job_events(
            job_id, level, event, stage, message, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            level,
            str(event),
            stage,
            str(message),
            _encode(details or {}),
            created_at or utc_now(),
        ),
    )


def _row_for_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(f"Analysis job not found: {job_id}")
    return row


def load_analysis_job(db_path: str | Path | None, job_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        return _job_dict(_row_for_job(conn, job_id))


def find_active_analysis_job(
    db_path: str | Path | None,
    *,
    source_id: str | None = None,
    source_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    clauses = ["status IN ('queued', 'running', 'awaiting_input')"]
    params: list[Any] = []
    if source_id is not None:
        clauses.append("source_id = ?")
        params.append(str(source_id))
    if source_fingerprint is not None:
        clauses.append("source_fingerprint = ?")
        params.append(str(source_fingerprint))
    with connect(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM analysis_jobs WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_at DESC, created_at DESC LIMIT 1",
            params,
        ).fetchone()
    return _job_dict(row) if row is not None else None


def create_analysis_job(
    db_path: str | Path | None,
    source: dict[str, Any],
    config: dict[str, Any],
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    job_id = job_id or uuid.uuid4().hex
    now = utc_now()
    try:
        with connect(db_path) as conn:
            persisted_source = conn.execute(
                "SELECT fingerprint FROM sources WHERE id = ?",
                (str(source["id"]),),
            ).fetchone()
            if persisted_source is None:
                raise KeyError(f"Source not found: {source['id']}")
            if str(persisted_source["fingerprint"]) != str(source["fingerprint"]):
                raise ValueError("The source ID and fingerprint do not identify the same source.")
            conn.execute(
                """
                INSERT INTO analysis_jobs(
                    id, source_id, source_fingerprint, status, stage, progress,
                    message, config_json, timings_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', 'queued', 0.0, ?, ?, '{}', ?, ?)
                """,
                (
                    job_id,
                    str(source["id"]),
                    str(source["fingerprint"]),
                    "Analysis queued",
                    _encode(config),
                    now,
                    now,
                ),
            )
            _event(conn, job_id, "job.created", stage="queued", message="Analysis queued", created_at=now)
    except sqlite3.IntegrityError as exc:
        active = find_active_analysis_job(
            db_path,
            source_id=str(source["id"]),
        )
        if active is not None:
            raise ActiveAnalysisJobError(active) from exc
        raise
    return load_analysis_job(db_path, job_id)


def start_analysis_job(db_path: str | Path | None, job_id: str) -> dict[str, Any]:
    now = utc_now()
    with connect(db_path) as conn:
        updated = conn.execute(
            """
            UPDATE analysis_jobs
            SET status = 'running', stage = 'starting', message = 'Starting analysis',
                started_at = COALESCE(started_at, ?), updated_at = ?,
                error_type = NULL, error_message = NULL
            WHERE id = ? AND status IN ('queued', 'awaiting_input')
            """,
            (now, now, job_id),
        )
        if updated.rowcount != 1:
            current = _job_dict(_row_for_job(conn, job_id))
            raise AnalysisJobStateError(
                f"Cannot start analysis job {job_id} while it is {current['status']}."
            )
        _event(
            conn,
            job_id,
            "job.started",
            stage="starting",
            message="Starting analysis",
            created_at=now,
        )
        row = _row_for_job(conn, job_id)
    return _job_dict(row)


def update_analysis_job_progress(
    db_path: str | Path | None,
    job_id: str,
    *,
    stage: str,
    progress: float,
    message: str,
    timings: dict[str, float] | None = None,
) -> dict[str, Any]:
    stage = str(stage).strip()
    if not stage:
        raise ValueError("Analysis job stage cannot be empty.")
    progress = float(progress)
    if not 0.0 <= progress <= 1.0:
        raise ValueError("Analysis job progress must be between 0 and 1.")
    now = utc_now()
    with connect(db_path) as conn:
        current = _row_for_job(conn, job_id)
        if current["status"] != "running":
            raise AnalysisJobStateError(
                f"Cannot update analysis job {job_id} while it is {current['status']}."
            )
        merged_timings = _merge_timings(current["timings_json"], timings)
        updated = conn.execute(
            """
            UPDATE analysis_jobs
            SET stage = ?, progress = ?, message = ?, timings_json = ?, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (stage, progress, str(message), _encode(merged_timings), now, job_id),
        )
        if updated.rowcount != 1:
            latest = _job_dict(_row_for_job(conn, job_id))
            raise AnalysisJobStateError(
                f"Cannot update analysis job {job_id} while it is {latest['status']}."
            )
        if stage != current["stage"]:
            _event(
                conn,
                job_id,
                "stage.started",
                stage=stage,
                message=str(message),
                details={"progress": progress},
                created_at=now,
            )
        row = _row_for_job(conn, job_id)
    return _job_dict(row)


def heartbeat_analysis_job(
    db_path: str | Path | None,
    job_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Refresh a running worker's lease without adding a noisy event row."""
    heartbeat_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamp = heartbeat_at.isoformat(timespec="seconds")
    with connect(db_path) as conn:
        updated = conn.execute(
            "UPDATE analysis_jobs SET updated_at = ? WHERE id = ? AND status = 'running'",
            (timestamp, job_id),
        )
        if updated.rowcount != 1:
            _row_for_job(conn, job_id)
            return False
    return True


def record_analysis_job_event(
    db_path: str | Path | None,
    job_id: str,
    event: str,
    *,
    level: str = "info",
    stage: str | None = None,
    message: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    with connect(db_path) as conn:
        _row_for_job(conn, job_id)
        _event(
            conn,
            job_id,
            event,
            level=level,
            stage=stage,
            message=message,
            details=details,
        )


def mark_analysis_job_awaiting_input(
    db_path: str | Path | None,
    job_id: str,
    *,
    message: str,
) -> dict[str, Any]:
    now = utc_now()
    with connect(db_path) as conn:
        updated = conn.execute(
            """
            UPDATE analysis_jobs
            SET status = 'awaiting_input', stage = 'model_resolution',
                message = ?, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (str(message), now, job_id),
        )
        if updated.rowcount != 1:
            current = _job_dict(_row_for_job(conn, job_id))
            raise AnalysisJobStateError(
                f"Cannot pause analysis job {job_id} while it is {current['status']}."
            )
        _event(
            conn,
            job_id,
            "model.input_required",
            level="warning",
            stage="model_resolution",
            message=str(message),
            created_at=now,
        )
        row = _row_for_job(conn, job_id)
    return _job_dict(row)


def complete_analysis_job(
    db_path: str | Path | None,
    job_id: str,
    analysis_id: str,
    *,
    message: str = "Analysis complete",
    timings: dict[str, float] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    with connect(db_path) as conn:
        current = _row_for_job(conn, job_id)
        if current["status"] != "running":
            raise AnalysisJobStateError(
                f"Cannot complete analysis job {job_id} while it is {current['status']}."
            )
        analysis_source = conn.execute(
            "SELECT source_id, source_fingerprint FROM analyses WHERE id = ?",
            (analysis_id,),
        ).fetchone()
        if analysis_source is None:
            raise KeyError(f"Analysis not found: {analysis_id}")
        if (
            str(analysis_source["source_id"]) != str(current["source_id"])
            or str(analysis_source["source_fingerprint"]) != str(current["source_fingerprint"])
        ):
            raise ValueError("The completed analysis belongs to a different source than this job.")
        merged_timings = _merge_timings(current["timings_json"], timings)
        updated = conn.execute(
            """
            UPDATE analysis_jobs
            SET status = 'completed', stage = 'complete', progress = 1.0,
                message = ?, timings_json = ?, analysis_id = ?,
                updated_at = ?, finished_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (str(message), _encode(merged_timings), analysis_id, now, now, job_id),
        )
        if updated.rowcount != 1:
            latest = _job_dict(_row_for_job(conn, job_id))
            raise AnalysisJobStateError(
                f"Cannot complete analysis job {job_id} while it is {latest['status']}."
            )
        _event(
            conn,
            job_id,
            "job.completed",
            stage="complete",
            message=str(message),
            details={"analysis_id": analysis_id},
            created_at=now,
        )
        row = _row_for_job(conn, job_id)
    return _job_dict(row)


def fail_analysis_job(
    db_path: str | Path | None,
    job_id: str,
    error: BaseException,
    *,
    timings: dict[str, float] | None = None,
) -> bool:
    now = utc_now()
    error_type = type(error).__name__
    message = str(error)
    with connect(db_path) as conn:
        current = _row_for_job(conn, job_id)
        merged_timings = _merge_timings(current["timings_json"], timings)
        updated = conn.execute(
            """
            UPDATE analysis_jobs
            SET status = 'failed', stage = 'failed', message = ?,
                error_type = ?, error_message = ?, timings_json = ?,
                updated_at = ?, finished_at = ?
            WHERE id = ? AND status IN ('queued', 'running', 'awaiting_input')
            """,
            (message, error_type, message, _encode(merged_timings), now, now, job_id),
        )
        if updated.rowcount != 1:
            return False
        _event(
            conn,
            job_id,
            "job.failed",
            level="error",
            stage="failed",
            message=message,
            details={"error_type": error_type},
            created_at=now,
        )
    return True


def cancel_analysis_job(db_path: str | Path | None, job_id: str) -> bool:
    """Cancel only work that has not started or is safely waiting for input."""
    now = utc_now()
    with connect(db_path) as conn:
        updated = conn.execute(
            """
            UPDATE analysis_jobs
            SET status = 'cancelled', stage = 'cancelled', message = 'Analysis cancelled',
                updated_at = ?, finished_at = ?
            WHERE id = ? AND status IN ('queued', 'awaiting_input')
            """,
            (now, now, job_id),
        )
        if updated.rowcount != 1:
            _row_for_job(conn, job_id)
            return False
        _event(
            conn,
            job_id,
            "job.cancelled",
            stage="cancelled",
            message="Analysis cancelled",
            created_at=now,
        )
    return True


def interrupt_analysis_job(
    db_path: str | Path | None,
    job_id: str,
    *,
    message: str,
) -> bool:
    """Record that a running worker disappeared; this does not cancel live work."""
    now = utc_now()
    with connect(db_path) as conn:
        updated = conn.execute(
            """
            UPDATE analysis_jobs
            SET status = 'interrupted', stage = 'interrupted', message = ?,
                updated_at = ?, finished_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (str(message), now, now, job_id),
        )
        if updated.rowcount != 1:
            _row_for_job(conn, job_id)
            return False
        _event(
            conn,
            job_id,
            "job.interrupted",
            level="warning",
            stage="interrupted",
            message=str(message),
            created_at=now,
        )
    return True


def list_analysis_job_events(
    db_path: str | Path | None,
    job_id: str,
) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        _row_for_job(conn, job_id)
        rows = conn.execute(
            "SELECT * FROM analysis_job_events WHERE job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "job_id": str(row["job_id"]),
            "level": str(row["level"]),
            "event": str(row["event"]),
            "stage": row["stage"],
            "message": str(row["message"]),
            "details": _decode(row["details_json"], {}),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def recover_interrupted_analysis_jobs(
    db_path: str | Path | None,
    job_ids: Iterable[str],
    *,
    message: str = "Analysis worker stopped before the run finished",
) -> list[str]:
    recovered: list[str] = []
    for job_id in job_ids:
        if interrupt_analysis_job(db_path, str(job_id), message=message):
            recovered.append(str(job_id))
    return recovered


def recover_stale_analysis_jobs(
    db_path: str | Path | None,
    *,
    now: datetime | None = None,
    stale_after_seconds: float = ANALYSIS_JOB_STALE_AFTER_SECONDS,
) -> list[str]:
    """Atomically interrupt running jobs whose worker lease has expired."""
    stale_after_seconds = float(stale_after_seconds)
    if stale_after_seconds <= 0.0:
        raise ValueError("Analysis-job stale timeout must be positive.")
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = (observed_at - timedelta(seconds=stale_after_seconds)).isoformat(
        timespec="seconds"
    )
    recovered_at = observed_at.isoformat(timespec="seconds")
    recovered: list[str] = []
    message = "Analysis worker heartbeat expired before the run finished"
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, updated_at
            FROM analysis_jobs
            WHERE status = 'running' AND updated_at <= ?
            ORDER BY updated_at, created_at
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            job_id = str(row["id"])
            updated = conn.execute(
                """
                UPDATE analysis_jobs
                SET status = 'interrupted', stage = 'interrupted', message = ?,
                    updated_at = ?, finished_at = ?
                WHERE id = ? AND status = 'running' AND updated_at <= ?
                """,
                (message, recovered_at, recovered_at, job_id, cutoff),
            )
            if updated.rowcount != 1:
                continue
            _event(
                conn,
                job_id,
                "job.interrupted",
                level="warning",
                stage="interrupted",
                message=message,
                details={
                    "reason": "heartbeat_expired",
                    "last_heartbeat_at": str(row["updated_at"]),
                    "stale_before": cutoff,
                },
                created_at=recovered_at,
            )
            recovered.append(job_id)
    return recovered
