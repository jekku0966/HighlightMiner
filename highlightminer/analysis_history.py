from __future__ import annotations

from pathlib import Path

from .diagnostics import log_event
from .storage import connect

class AnalysisDeletionBlocked(RuntimeError):
    """An active worker still depends on the selected analysis or source."""


def _deletion_impact(conn, analysis_id: str) -> dict:
    analysis = conn.execute(
        """
        SELECT a.id, a.video_name, a.content_label, a.run_number, a.source_id,
               a.source_fingerprint, m.value AS analysis_title
        FROM analyses a
        LEFT JOIN metadata m ON m.key = ?
        WHERE a.id = ?
        """,
        (f"analysis_title:{analysis_id}", analysis_id),
    ).fetchone()
    if analysis is None:
        raise KeyError(f"Analysis not found: {analysis_id}")

    reviews = conn.execute(
        """
        SELECT
            COUNT(c.candidate_id) AS candidates,
            SUM(CASE WHEN r.status = 'keep' THEN 1 ELSE 0 END) AS kept,
            SUM(CASE WHEN r.status = 'reject' THEN 1 ELSE 0 END) AS rejected,
            SUM(CASE WHEN r.status = 'unreviewed' THEN 1 ELSE 0 END) AS unreviewed
        FROM candidates c
        LEFT JOIN reviews r
            ON r.analysis_id = c.analysis_id AND r.candidate_id = c.candidate_id
        WHERE c.analysis_id = ?
        """,
        (analysis_id,),
    ).fetchone()
    related = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM review_events WHERE analysis_id = ?) AS review_events,
            (SELECT COUNT(*) FROM exports WHERE analysis_id = ?) AS exports,
            (SELECT COUNT(*) FROM transcript_segments WHERE analysis_id = ?) AS transcript_segments,
            (SELECT COUNT(*) FROM audio_features WHERE analysis_id = ?) AS audio_features,
            (SELECT COUNT(*) FROM chat_features WHERE analysis_id = ?) AS chat_features,
            (SELECT COUNT(*) FROM export_queue_items WHERE analysis_id = ?) AS queue_items,
            (SELECT COUNT(*) FROM export_queue_items
             WHERE analysis_id = ? AND status = 'exporting') AS exporting_items
        """,
        (analysis_id,) * 7,
    ).fetchone()
    return {
        "analysis_id": str(analysis["id"]),
        "analysis_title": str(analysis["analysis_title"] or ""),
        "video_name": str(analysis["video_name"]),
        "content_label": str(analysis["content_label"]),
        "run_number": int(analysis["run_number"] or 1),
        "source_id": str(analysis["source_id"] or ""),
        "source_fingerprint": str(analysis["source_fingerprint"] or ""),
        "candidates": int(reviews["candidates"] or 0),
        "kept": int(reviews["kept"] or 0),
        "rejected": int(reviews["rejected"] or 0),
        "unreviewed": int(reviews["unreviewed"] or 0),
        "review_events": int(related["review_events"] or 0),
        "exports": int(related["exports"] or 0),
        "transcript_segments": int(related["transcript_segments"] or 0),
        "audio_features": int(related["audio_features"] or 0),
        "chat_features": int(related["chat_features"] or 0),
        "queue_items": int(related["queue_items"] or 0),
        "exporting_items": int(related["exporting_items"] or 0),
    }


def analysis_deletion_impact(db_path: str | Path | None, analysis_id: str) -> dict:
    """Describe exactly which stored records a confirmed deletion will remove."""
    with connect(db_path) as conn:
        return _deletion_impact(conn, str(analysis_id))


def delete_analysis(
    db_path: str | Path | None,
    analysis_id: str,
    *,
    acknowledged: bool,
    confirmed_analysis_id: str,
) -> dict:
    """Delete one immutable completed analysis after explicit acknowledgement and confirmation."""
    analysis_id = str(analysis_id)
    if acknowledged is not True:
        raise ValueError("Deletion requires explicit acknowledgement of permanent data loss.")
    if str(confirmed_analysis_id) != analysis_id:
        raise ValueError("The deletion confirmation does not match the selected analysis.")

    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        impact = _deletion_impact(conn, analysis_id)
        if impact["exporting_items"]:
            raise AnalysisDeletionBlocked("This analysis has a clip in the active export batch.")
        source_id = impact["source_id"]
        if source_id:
            active_job = conn.execute(
                """
                SELECT 1 FROM analysis_jobs
                WHERE source_id = ? AND status IN ('queued', 'running', 'awaiting_input')
                LIMIT 1
                """,
                (source_id,),
            ).fetchone()
            if active_job is not None:
                raise AnalysisDeletionBlocked(
                    "This source has an active analysis job. Wait for it to finish before deleting history."
                )

        conn.execute("DELETE FROM metadata WHERE key = ?", (f"analysis_title:{analysis_id}",))
        deleted = conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        if deleted.rowcount != 1:
            raise KeyError(f"Analysis not found: {analysis_id}")
        conn.commit()

    log_event(
        "analysis.deleted",
        analysis_id=analysis_id,
        source_id=impact["source_id"],
        candidates=impact["candidates"],
        review_events=impact["review_events"],
        exports=impact["exports"],
        queue_items=impact["queue_items"],
    )
    return impact
