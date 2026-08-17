from __future__ import annotations

from pathlib import Path

from .storage import load_review as _load_review
from .storage import save_review as _save_review


def default_review(analysis: dict) -> dict:
    return {
        "version": 2,
        "items": {
            c["id"]: {
                "status": "unreviewed",
                "start": c["start"],
                "end": c["end"],
                "title": "",
                "reviewed_at": None,
                "exported_at": None,
                "export_path": None,
            }
            for c in analysis.get("candidates", [])
        },
    }


def load_review(
    db_path: str | Path | None,
    analysis_id: str,
    analysis: dict | None = None,
) -> dict:
    return _load_review(db_path, analysis_id, analysis)


def save_review(
    db_path: str | Path | None,
    analysis_id: str,
    review: dict,
) -> None:
    _save_review(db_path, analysis_id, review)
