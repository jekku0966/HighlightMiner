from __future__ import annotations

import logging
from pathlib import Path

from .diagnostics import log_event
from .storage import load_analysis as _load_analysis
from .storage import load_review as _load_review
from .storage import save_review as _save_review
from .timestamps import normalize_clip_bounds


def default_review(analysis: dict) -> dict:
    duration = float(analysis.get("duration", 0.0))
    items = {}
    for candidate in analysis.get("candidates", []):
        bounds = normalize_clip_bounds(candidate["start"], candidate["end"], duration)
        items[candidate["id"]] = {
            "status": "unreviewed",
            "start": bounds.start,
            "end": bounds.end,
            "title": "",
            "reviewed_at": None,
            "exported_at": None,
            "export_path": None,
        }
    return {"version": 2, "items": items}


def _normalize_review_items(
    review: dict,
    source_duration: float,
    *,
    analysis_id: str | None = None,
    log_meaningful_changes: bool = False,
) -> dict:
    normalized = {"version": int(review.get("version", 2)), "items": {}}
    for candidate_id, item in review.get("items", {}).items():
        updated = dict(item)
        bounds = normalize_clip_bounds(
            item.get("start", 0.0),
            item.get("end", 0.0),
            source_duration,
        )
        updated["start"] = bounds.start
        updated["end"] = bounds.end
        normalized["items"][candidate_id] = updated
        if log_meaningful_changes and bounds.meaningfully_invalid:
            log_event(
                "clip.bounds_normalized",
                level=logging.WARNING,
                analysis_id=str(analysis_id or ""),
                candidate_id=str(candidate_id),
            )
    return normalized


def load_review(
    db_path: str | Path | None,
    analysis_id: str,
    analysis: dict | None = None,
) -> dict:
    review = _load_review(db_path, analysis_id, analysis)
    if analysis is None:
        return review
    return _normalize_review_items(review, float(analysis["duration"]))


def save_review(
    db_path: str | Path | None,
    analysis_id: str,
    review: dict,
) -> None:
    analysis = _load_analysis(db_path, analysis_id)
    normalized = _normalize_review_items(
        review,
        float(analysis["duration"]),
        analysis_id=analysis_id,
        log_meaningful_changes=True,
    )
    for candidate_id, item in normalized["items"].items():
        if candidate_id in review.get("items", {}):
            review["items"][candidate_id]["start"] = item["start"]
            review["items"][candidate_id]["end"] = item["end"]
    _save_review(db_path, analysis_id, normalized)
