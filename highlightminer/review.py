from __future__ import annotations

from pathlib import Path

from .util import load_json, save_json


def default_review(analysis: dict) -> dict:
    return {
        "version": 1,
        "items": {
            c["id"]: {
                "status": "unreviewed",
                "start": c["start"],
                "end": c["end"],
                "title": "",
            }
            for c in analysis.get("candidates", [])
        },
    }


def load_review(path: str | Path, analysis: dict) -> dict:
    p = Path(path)
    review = load_json(p) if p.exists() else default_review(analysis)
    review.setdefault("items", {})
    for c in analysis.get("candidates", []):
        review["items"].setdefault(c["id"], {
            "status": "unreviewed", "start": c["start"], "end": c["end"], "title": ""
        })
    return review


def save_review(path: str | Path, review: dict) -> None:
    save_json(path, review)
