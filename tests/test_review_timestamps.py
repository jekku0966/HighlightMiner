from __future__ import annotations

import pytest

from highlightminer import review as review_module


def test_default_review_clamps_candidate_to_analysis_duration() -> None:
    duration = 15959.001859
    review = review_module.default_review(
        {
            "duration": duration,
            "candidates": [{"id": "H001", "start": 15958.0, "end": 15959.002}],
        }
    )

    assert review["items"]["H001"]["start"] == 15958.0
    assert review["items"]["H001"]["end"] == duration


def test_load_review_normalizes_existing_items(monkeypatch) -> None:
    stored = {
        "version": 2,
        "items": {
            "H001": {
                "status": "keep",
                "start": -5.0,
                "end": 120.0,
                "title": "Clutch",
            }
        },
    }
    monkeypatch.setattr(review_module, "_load_review", lambda *_args: stored)

    loaded = review_module.load_review(None, "analysis-123", {"duration": 100.0})

    assert loaded["items"]["H001"]["start"] == 0.0
    assert loaded["items"]["H001"]["end"] == 100.0
    assert stored["items"]["H001"]["start"] == -5.0
    assert stored["items"]["H001"]["end"] == 120.0


def test_save_review_repairs_and_logs_reversed_eof_range(monkeypatch) -> None:
    review = {
        "version": 2,
        "items": {
            "H001": {
                "status": "keep",
                "start": 99.98,
                "end": 99.0,
                "title": "Clutch",
            }
        },
    }
    saved: list[dict] = []
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(review_module, "_load_analysis", lambda *_args: {"duration": 100.0})
    monkeypatch.setattr(review_module, "_save_review", lambda *_args: saved.append(_args[-1]))
    monkeypatch.setattr(review_module, "log_event", lambda event, **fields: events.append((event, fields)))

    review_module.save_review(None, "analysis-123", review)

    item = review["items"]["H001"]
    assert item["start"] == pytest.approx(99.9)
    assert item["end"] == 100.0
    assert saved[0]["items"]["H001"]["start"] == pytest.approx(99.9)
    assert events == [
        (
            "clip.bounds_normalized",
            {
                "level": review_module.logging.WARNING,
                "analysis_id": "analysis-123",
                "candidate_id": "H001",
            },
        )
    ]

