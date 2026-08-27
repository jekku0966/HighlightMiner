from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from highlightminer.export_queue import (
    ExportBatchAlreadyRunning,
    ExportQueueStateError,
    clear_export_queue,
    complete_export_queue_item,
    enqueue_export_items,
    fail_export_queue_item,
    finish_export_batch,
    interrupt_export_batch,
    list_export_queue,
    recover_stale_export_batches,
    remove_export_queue_item,
    retry_failed_export_items,
    start_export_batch,
    update_export_queue_title,
)
from highlightminer.storage import connect, load_analysis, load_review, save_analysis


def _saved_analysis(tmp_path: Path) -> tuple[Path, dict]:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"source video")
    db = tmp_path / "highlightminer.db"
    payload = {
        "version": 2,
        "video_path": str(video),
        "content_label": "Overwatch 2",
        "duration": 120.0,
        "media": {"duration": 120.0},
        "transcription": {"language": "en"},
        "chat": {"path": None, "messages": 0},
        "settings": {},
        "candidates": [
            {
                "id": "H001",
                "rank": 1,
                "score": 0.9,
                "peak_time": 42.0,
                "start": 30.0,
                "end": 60.0,
                "audio_score": 0.8,
                "transcript_score": 0.7,
                "chat_score": 0.2,
                "reason": "reaction",
                "transcript": "wow",
                "content_label": "Overwatch 2",
            },
            {
                "id": "H002",
                "rank": 2,
                "score": 0.8,
                "peak_time": 80.0,
                "start": 70.0,
                "end": 95.0,
                "audio_score": 0.7,
                "transcript_score": 0.6,
                "chat_score": 0.1,
                "reason": "audio spike",
                "transcript": "",
                "content_label": "Overwatch 2",
            },
        ],
    }
    analysis_id = save_analysis(
        db,
        payload,
        transcript=[],
        audio_features=[],
        chat_features=[],
        work_dir=tmp_path,
    )
    return db, load_analysis(db, analysis_id)


def _queue(db: Path, analysis: dict, *candidate_ids: str) -> dict[str, int]:
    candidates = {item["id"]: item for item in analysis["candidates"]}
    return enqueue_export_items(
        db,
        analysis,
        [
            {
                "candidate_id": candidate_id,
                "start": candidates[candidate_id]["start"],
                "end": candidates[candidate_id]["end"],
                "title": "Clutch" if candidate_id == "H001" else "",
            }
            for candidate_id in candidate_ids
        ],
        Path(analysis["work_dir"]) / "clips",
    )


def test_queue_persists_items_and_suppresses_duplicate_candidates(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)

    assert _queue(db, analysis, "H001", "H002") == {"added": 2, "skipped": 0}
    assert _queue(db, analysis, "H001") == {"added": 0, "skipped": 1}

    items = list_export_queue(db)
    assert [item["candidate_id"] for item in items] == ["H001", "H002"]
    assert items[0]["source_name"] == "vod.mp4"
    assert items[0]["start"] == 30.0
    assert items[0]["title"] == "Clutch"


def test_queue_does_not_misreport_foreign_key_failures_as_duplicates(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        enqueue_export_items(
            db,
            analysis,
            [{"candidate_id": "missing", "start": 1.0, "end": 2.0}],
            tmp_path / "clips",
        )

    assert list_export_queue(db) == []


def test_queue_item_can_be_edited_or_removed_before_export(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)
    _queue(db, analysis, "H001", "H002")
    first, second = list_export_queue(db)

    update_export_queue_title(db, first["id"], "  Better title  ")
    assert remove_export_queue_item(db, second["id"]) is True

    items = list_export_queue(db)
    assert len(items) == 1
    assert items[0]["title"] == "Better title"


def test_batch_claim_is_atomic_and_prevents_duplicate_starts(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)
    _queue(db, analysis, "H001")

    batch, items = start_export_batch(db)

    assert batch["status"] == "running"
    assert items[0]["status"] == "exporting"
    with pytest.raises(ExportBatchAlreadyRunning):
        start_export_batch(db)
    with pytest.raises(ExportQueueStateError):
        clear_export_queue(db)
    with pytest.raises(ExportQueueStateError):
        update_export_queue_title(db, items[0]["id"], "too late")
    assert remove_export_queue_item(db, items[0]["id"]) is False


def test_successful_item_updates_queue_review_and_export_history_atomically(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)
    _queue(db, analysis, "H001")
    batch, items = start_export_batch(db)
    output = tmp_path / "clips" / "Overwatch 2" / "Clutch.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"clip")

    complete_export_queue_item(db, batch["id"], items[0]["id"], output)
    finished = finish_export_batch(db, batch["id"])

    assert finished["status"] == "completed"
    queued = list_export_queue(db)[0]
    assert queued["status"] == "completed"
    assert queued["output_path"] == str(output.resolve())
    review = load_review(db, analysis["analysis_id"], analysis)
    assert review["items"]["H001"]["export_path"] == str(output.resolve())
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 1


def test_failed_items_remain_available_for_explicit_retry(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)
    _queue(db, analysis, "H001")
    batch, items = start_export_batch(db)

    fail_export_queue_item(db, batch["id"], items[0]["id"], RuntimeError("encoder failed"))
    finished = finish_export_batch(db, batch["id"])

    assert finished["status"] == "failed"
    assert list_export_queue(db)[0]["error_message"] == "encoder failed"
    assert retry_failed_export_items(db) == 1


def test_unexpected_worker_error_interrupts_batch_and_keeps_items_retryable(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)
    _queue(db, analysis, "H001", "H002")
    batch, _items = start_export_batch(db)

    assert interrupt_export_batch(db, batch["id"], RuntimeError("worker crashed")) is True

    items = list_export_queue(db)
    assert {item["status"] for item in items} == {"failed"}
    assert {item["error_message"] for item in items} == {"worker crashed"}
    assert retry_failed_export_items(db) == 2
    retried = list_export_queue(db)[0]
    assert retried["status"] == "queued"
    assert retried["error_message"] is None


def test_one_failed_clip_does_not_discard_successful_siblings(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)
    _queue(db, analysis, "H001", "H002")
    batch, items = start_export_batch(db)
    first, second = items
    output = tmp_path / "clips" / "Overwatch 2" / "H002.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"clip")

    fail_export_queue_item(db, batch["id"], first["id"], RuntimeError("first failed"))
    complete_export_queue_item(db, batch["id"], second["id"], output)
    finished = finish_export_batch(db, batch["id"])

    assert finished["status"] == "failed"
    assert finished["completed_items"] == 1
    assert finished["failed_items"] == 1
    statuses = {item["candidate_id"]: item["status"] for item in list_export_queue(db)}
    assert statuses == {"H001": "failed", "H002": "completed"}


def test_expired_worker_is_recovered_without_discarding_queue_items(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)
    _queue(db, analysis, "H001")
    batch, _items = start_export_batch(db)
    with connect(db) as conn:
        conn.execute(
            "UPDATE export_batches SET updated_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (batch["id"],),
        )
        conn.commit()

    recovered = recover_stale_export_batches(
        db,
        stale_after_seconds=30.0,
        now=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )

    assert recovered == [batch["id"]]
    item = list_export_queue(db)[0]
    assert item["status"] == "failed"
    assert "heartbeat expired" in item["error_message"]
    assert retry_failed_export_items(db) == 1


def test_clear_queue_keeps_export_files_and_history(tmp_path: Path) -> None:
    db, analysis = _saved_analysis(tmp_path)
    _queue(db, analysis, "H001")
    batch, items = start_export_batch(db)
    output = tmp_path / "clips" / "Overwatch 2" / "Clutch.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"clip")
    complete_export_queue_item(db, batch["id"], items[0]["id"], output)
    finish_export_batch(db, batch["id"])

    assert clear_export_queue(db) == 1
    assert output.exists()
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 1
