from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .diagnostics import log_event, log_exception
from .shutdown import ensure_work_admitted
from .storage import connect, utc_now

EXPORT_BATCH_HEARTBEAT_INTERVAL_SECONDS = 5.0
EXPORT_BATCH_STALE_AFTER_SECONDS = 120.0


class ExportQueueStateError(RuntimeError):
    """The requested queue transition is not valid for its persisted state."""


class ExportBatchAlreadyRunning(ExportQueueStateError):
    """Another session already owns the active export batch."""


def _dict(row) -> dict:
    return dict(row) if row is not None else {}


def enqueue_export_items(
    db_path: str | Path | None,
    analysis: dict,
    items: Iterable[dict],
    export_dir: str | Path,
) -> dict[str, int]:
    """Persist immutable clip ranges while skipping candidates already queued."""
    analysis_id = str(analysis.get("analysis_id") or "")
    if not analysis_id:
        raise ValueError("An analysis ID is required to queue exports.")
    source_path = str(Path(str(analysis["video_path"])).expanduser().resolve())
    source_name = str(analysis.get("video_name") or Path(source_path).name)
    default_label = str(analysis.get("content_label") or "Uncategorized")
    destination = str(Path(export_dir).expanduser().resolve())
    duration = float(analysis.get("duration", 0.0))
    now = utc_now()
    added = 0
    skipped = 0

    with connect(db_path) as conn:
        for raw in items:
            candidate_id = str(raw.get("candidate_id") or raw.get("id") or "").strip()
            if not candidate_id:
                raise ValueError("A candidate ID is required to queue an export.")
            start = float(raw["start"])
            end = float(raw["end"])
            if start < 0.0 or end <= start or (duration > 0.0 and end > duration):
                raise ValueError(f"Invalid export range for {candidate_id}: {start}–{end}.")
            cursor = conn.execute(
                """
                INSERT INTO export_queue_items(
                    id, analysis_id, candidate_id, source_path, source_name,
                    content_label, start, end, title, export_dir, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                ON CONFLICT(analysis_id, candidate_id) DO NOTHING
                """,
                (
                    uuid.uuid4().hex,
                    analysis_id,
                    candidate_id,
                    source_path,
                    source_name,
                    str(raw.get("content_label") or default_label),
                    start,
                    end,
                    str(raw.get("title") or "").strip()[:500],
                    destination,
                    now,
                    now,
                ),
            )
            if cursor.rowcount:
                added += 1
            else:
                skipped += 1
        conn.commit()
    log_event("export.queue_updated", added=added, duplicates_skipped=skipped)
    return {"added": added, "skipped": skipped}


def list_export_queue(db_path: str | Path | None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM export_queue_items
            ORDER BY
                CASE status
                    WHEN 'exporting' THEN 0
                    WHEN 'queued' THEN 1
                    WHEN 'failed' THEN 2
                    ELSE 3
                END,
                created_at,
                rowid
            """
        ).fetchall()
    return [_dict(row) for row in rows]


def update_export_queue_title(
    db_path: str | Path | None,
    item_id: str,
    title: str,
) -> None:
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE export_queue_items SET title = ?, updated_at = ?
            WHERE id = ? AND status <> 'exporting'
            """,
            (str(title).strip()[:500], utc_now(), item_id),
        )
        if not cursor.rowcount:
            exists = conn.execute(
                "SELECT 1 FROM export_queue_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(f"Export queue item not found: {item_id}")
            raise ExportQueueStateError("An exporting item cannot be edited.")
        conn.commit()


def remove_export_queue_item(db_path: str | Path | None, item_id: str) -> bool:
    with connect(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM export_queue_items WHERE id = ? AND status <> 'exporting'",
            (item_id,),
        )
        conn.commit()
    return bool(cursor.rowcount)


def clear_export_queue(db_path: str | Path | None) -> int:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT 1 FROM export_batches WHERE status = 'running' LIMIT 1"
        ).fetchone()
        if active is not None:
            raise ExportQueueStateError("The export queue cannot be cleared while a batch is running.")
        cursor = conn.execute("DELETE FROM export_queue_items")
        conn.commit()
    return int(cursor.rowcount)


def retry_failed_export_items(db_path: str | Path | None) -> int:
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT 1 FROM export_batches WHERE status = 'running' LIMIT 1"
        ).fetchone()
        if active is not None:
            raise ExportQueueStateError("Failed exports cannot be retried while a batch is running.")
        cursor = conn.execute(
            """
            UPDATE export_queue_items
            SET status = 'queued', batch_id = NULL, error_message = NULL,
                started_at = NULL, finished_at = NULL, updated_at = ?
            WHERE status = 'failed'
            """,
            (now,),
        )
        conn.commit()
    return int(cursor.rowcount)


def load_active_export_batch(db_path: str | Path | None) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM export_batches WHERE status = 'running' ORDER BY started_at LIMIT 1"
        ).fetchone()
    return _dict(row) if row is not None else None


def start_export_batch(db_path: str | Path | None) -> tuple[dict, list[dict]]:
    """Atomically claim every queued item for exactly one batch worker."""
    recover_stale_export_batches(db_path)
    now = utc_now()
    batch_id = uuid.uuid4().hex
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_work_admitted(conn)
        active = conn.execute(
            "SELECT id FROM export_batches WHERE status = 'running' LIMIT 1"
        ).fetchone()
        if active is not None:
            raise ExportBatchAlreadyRunning("An export batch is already running in another session.")
        rows = conn.execute(
            "SELECT * FROM export_queue_items WHERE status = 'queued' ORDER BY created_at, rowid"
        ).fetchall()
        if not rows:
            raise ExportQueueStateError("There are no queued clips to export.")
        conn.execute(
            """
            INSERT INTO export_batches(
                id, status, total_items, created_at, started_at, updated_at
            ) VALUES (?, 'running', ?, ?, ?, ?)
            """,
            (batch_id, len(rows), now, now, now),
        )
        claimed = conn.execute(
            """
            UPDATE export_queue_items
            SET status = 'exporting', batch_id = ?, started_at = ?, updated_at = ?
            WHERE status = 'queued'
            """,
            (batch_id, now, now),
        )
        if claimed.rowcount != len(rows):
            raise ExportQueueStateError("The queued export set changed while it was being claimed.")
        conn.commit()
    batch = load_active_export_batch(db_path)
    if batch is None:
        raise ExportQueueStateError("The export batch could not be persisted.")
    claimed = [{**_dict(row), "status": "exporting", "batch_id": batch_id} for row in rows]
    log_event("export.batch_start", batch_id=batch_id, total_items=len(claimed))
    return batch, claimed


def touch_export_batch(db_path: str | Path | None, batch_id: str) -> bool:
    with connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE export_batches SET updated_at = ? WHERE id = ? AND status = 'running'",
            (utc_now(), batch_id),
        )
        conn.commit()
    return bool(cursor.rowcount)


def _refresh_batch_counts(conn, batch_id: str) -> tuple[int, int]:
    counts = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
        FROM export_queue_items WHERE batch_id = ?
        """,
        (batch_id,),
    ).fetchone()
    completed = int(counts["completed"] or 0)
    failed = int(counts["failed"] or 0)
    conn.execute(
        """
        UPDATE export_batches
        SET completed_items = ?, failed_items = ?, updated_at = ?
        WHERE id = ? AND status = 'running'
        """,
        (completed, failed, utc_now(), batch_id),
    )
    return completed, failed


def complete_export_queue_item(
    db_path: str | Path | None,
    batch_id: str,
    item_id: str,
    output_path: str | Path,
) -> None:
    """Complete a queue item and its export history in one transaction."""
    now = utc_now()
    path = str(Path(output_path).expanduser().resolve())
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT analysis_id, candidate_id FROM export_queue_items
            WHERE id = ? AND batch_id = ? AND status = 'exporting'
            """,
            (item_id, batch_id),
        ).fetchone()
        if row is None:
            raise ExportQueueStateError("The export item is no longer owned by this batch.")
        conn.execute(
            """
            INSERT INTO exports(analysis_id, candidate_id, output_path, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (row["analysis_id"], row["candidate_id"], path, now),
        )
        conn.execute(
            """
            UPDATE reviews SET exported_at = ?, export_path = ?, updated_at = ?
            WHERE analysis_id = ? AND candidate_id = ?
            """,
            (now, path, now, row["analysis_id"], row["candidate_id"]),
        )
        conn.execute(
            """
            UPDATE export_queue_items
            SET status = 'completed', output_path = ?, error_message = NULL,
                finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (path, now, now, item_id),
        )
        _refresh_batch_counts(conn, batch_id)
        conn.commit()


def fail_export_queue_item(
    db_path: str | Path | None,
    batch_id: str,
    item_id: str,
    error: BaseException | str,
) -> None:
    now = utc_now()
    message = str(error).strip()[:2000] or "Export failed"
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE export_queue_items
            SET status = 'failed', error_message = ?, finished_at = ?, updated_at = ?
            WHERE id = ? AND batch_id = ? AND status = 'exporting'
            """,
            (message, now, now, item_id, batch_id),
        )
        if not cursor.rowcount:
            raise ExportQueueStateError("The export item is no longer owned by this batch.")
        _refresh_batch_counts(conn, batch_id)
        conn.commit()
    if isinstance(error, BaseException):
        log_exception(
            "export.queue_item_failed",
            error,
            batch_id=batch_id,
            item_id=item_id,
        )
    else:
        log_event(
            "export.queue_item_failed",
            level=logging.ERROR,
            batch_id=batch_id,
            item_id=item_id,
            error_message=message,
        )


def finish_export_batch(db_path: str | Path | None, batch_id: str) -> dict:
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        remaining = int(
            conn.execute(
                "SELECT COUNT(*) FROM export_queue_items WHERE batch_id = ? AND status = 'exporting'",
                (batch_id,),
            ).fetchone()[0]
        )
        if remaining:
            raise ExportQueueStateError("The export batch still has unfinished items.")
        completed, failed = _refresh_batch_counts(conn, batch_id)
        status = "failed" if failed else "completed"
        message = (
            f"Exported {completed} clip(s); {failed} failed and can be retried."
            if failed
            else f"Exported {completed} clip(s)."
        )
        cursor = conn.execute(
            """
            UPDATE export_batches
            SET status = ?, message = ?, completed_items = ?, failed_items = ?,
                updated_at = ?, finished_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (status, message, completed, failed, now, now, batch_id),
        )
        if not cursor.rowcount:
            raise ExportQueueStateError("The export batch is no longer running.")
        row = conn.execute("SELECT * FROM export_batches WHERE id = ?", (batch_id,)).fetchone()
        conn.commit()
    result = _dict(row)
    log_event(
        "export.batch_complete",
        level=logging.WARNING if failed else logging.INFO,
        batch_id=batch_id,
        completed_items=completed,
        failed_items=failed,
    )
    return result


def interrupt_export_batch(
    db_path: str | Path | None,
    batch_id: str,
    error: BaseException | str,
) -> bool:
    """Fail unfinished items immediately after an unexpected worker error."""
    now = utc_now()
    message = str(error).strip()[:2000] or "Export worker interrupted"
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute(
            "SELECT status FROM export_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if batch is None or batch["status"] != "running":
            return False
        conn.execute(
            """
            UPDATE export_queue_items
            SET status = 'failed', error_message = ?, finished_at = ?, updated_at = ?
            WHERE batch_id = ? AND status = 'exporting'
            """,
            (message, now, now, batch_id),
        )
        completed, failed = _refresh_batch_counts(conn, batch_id)
        conn.execute(
            """
            UPDATE export_batches
            SET status = 'interrupted', message = ?, completed_items = ?, failed_items = ?,
                updated_at = ?, finished_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (message, completed, failed, now, now, batch_id),
        )
        conn.commit()
    if isinstance(error, BaseException):
        log_exception("export.batch_interrupted", error, batch_id=batch_id)
    else:
        log_event(
            "export.batch_interrupted",
            level=logging.ERROR,
            batch_id=batch_id,
            error_message=message,
        )
    return True


def recover_stale_export_batches(
    db_path: str | Path | None,
    *,
    stale_after_seconds: float = EXPORT_BATCH_STALE_AFTER_SECONDS,
    now: datetime | None = None,
) -> list[str]:
    threshold = (now or datetime.now(timezone.utc)) - timedelta(
        seconds=max(0.0, float(stale_after_seconds))
    )
    cutoff = threshold.isoformat(timespec="seconds")
    recovered: list[str] = []
    finished = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id FROM export_batches WHERE status = 'running' AND updated_at <= ?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            batch_id = str(row["id"])
            conn.execute(
                """
                UPDATE export_queue_items
                SET status = 'failed', error_message = 'Export worker heartbeat expired; retry this item.',
                    finished_at = ?, updated_at = ?
                WHERE batch_id = ? AND status = 'exporting'
                """,
                (finished, finished, batch_id),
            )
            _refresh_batch_counts(conn, batch_id)
            conn.execute(
                """
                UPDATE export_batches
                SET status = 'interrupted', message = 'Export worker heartbeat expired',
                    updated_at = ?, finished_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (finished, finished, batch_id),
            )
            recovered.append(batch_id)
        conn.commit()
    if recovered:
        log_event(
            "export.stale_batches_recovered",
            level=logging.WARNING,
            batch_ids=recovered,
        )
    return recovered


class ExportBatchHeartbeat:
    """Keep a synchronous export batch recoverable without permitting duplicates."""

    def __init__(self, db_path: str | Path | None, batch_id: str):
        self._db_path = db_path
        self._batch_id = batch_id
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not touch_export_batch(self._db_path, self._batch_id):
            raise ExportQueueStateError("The export batch is no longer running.")
        self._thread = threading.Thread(
            target=self._run,
            name=f"export-heartbeat-{self._batch_id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(EXPORT_BATCH_HEARTBEAT_INTERVAL_SECONDS):
            try:
                if not touch_export_batch(self._db_path, self._batch_id):
                    return
            except Exception as exc:
                log_exception(
                    "export.heartbeat_error",
                    exc,
                    batch_id=self._batch_id,
                )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
