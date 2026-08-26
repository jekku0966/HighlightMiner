from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from highlightminer.analysis_jobs import (
    ActiveAnalysisJobError,
    cancel_analysis_job,
    complete_analysis_job,
    create_analysis_job,
    fail_analysis_job,
    find_active_analysis_job,
    heartbeat_analysis_job,
    list_analysis_job_events,
    load_analysis_job,
    mark_analysis_job_awaiting_input,
    recover_interrupted_analysis_jobs,
    recover_stale_analysis_jobs,
    start_analysis_job,
    update_analysis_job_progress,
)
from highlightminer.storage import connect, register_source, save_analysis


def _source(db: Path, video: Path) -> dict:
    return register_source(
        db,
        {
            "fingerprint": f"fingerprint-{video.name}",
            "path": str(video),
            "video_name": video.name,
            "file_size": video.stat().st_size,
        },
    )


def _saved_analysis(db: Path, video: Path, source: dict) -> str:
    return save_analysis(
        db,
        {
            "version": 2,
            "video_path": str(video),
            "content_label": "Test",
            "duration": 1.0,
            "media": {"duration": 1.0},
            "transcription": {},
            "chat": {},
            "settings": {},
            "candidates": [],
        },
        [],
        [],
        [],
        work_dir=video.parent,
        source=source,
    )


def test_analysis_job_lifecycle_persists_progress_timings_and_events(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    source = _source(db, video)
    job = create_analysis_job(db, source, {"settings": {"beam_size": 5}})

    started = start_analysis_job(db, job["id"])
    assert started["status"] == "running"
    assert started["started_at"]

    updated = update_analysis_job_progress(
        db,
        job["id"],
        stage="transcription",
        progress=0.5,
        message="Transcribing",
        timings={"source_setup_seconds": 0.25},
    )
    assert updated["stage"] == "transcription"
    assert updated["progress"] == 0.5
    assert updated["timings"] == {"source_setup_seconds": 0.25}

    analysis_id = _saved_analysis(db, video, source)
    completed = complete_analysis_job(
        db,
        job["id"],
        analysis_id,
        timings={"pipeline_elapsed_seconds": 1.5},
    )
    assert completed["status"] == "completed"
    assert completed["analysis_id"] == analysis_id
    assert completed["progress"] == 1.0
    assert completed["finished_at"]
    assert completed["timings"] == {
        "source_setup_seconds": 0.25,
        "pipeline_elapsed_seconds": 1.5,
    }

    events = list_analysis_job_events(db, job["id"])
    assert [event["event"] for event in events] == [
        "job.created",
        "job.started",
        "stage.started",
        "job.completed",
    ]


def test_active_job_uniqueness_is_enforced_per_source(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    source = _source(db, video)
    first = create_analysis_job(db, source, {"settings": {"beam_size": 5}})

    with pytest.raises(ActiveAnalysisJobError) as raised:
        create_analysis_job(db, source, {"settings": {"beam_size": 1}})

    assert raised.value.job["id"] == first["id"]
    assert find_active_analysis_job(db, source_fingerprint=source["fingerprint"])["id"] == first["id"]
    assert find_active_analysis_job(db, source_id=source["id"])["id"] == first["id"]


def test_job_rejects_a_fingerprint_that_does_not_belong_to_the_source_id(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    source = _source(db, video)
    inconsistent = {**source, "fingerprint": "different-fingerprint"}

    with pytest.raises(ValueError, match="do not identify the same source"):
        create_analysis_job(db, inconsistent, {"run": 1})


def test_analysis_job_configuration_is_immutable(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    source = _source(db, video)
    job = create_analysis_job(db, source, {"settings": {"beam_size": 5}})

    with pytest.raises(sqlite3.IntegrityError, match="configuration is immutable"):
        with connect(db) as conn:
            conn.execute(
                "UPDATE analysis_jobs SET config_json = ? WHERE id = ?",
                ('{"settings":{"beam_size":1}}', job["id"]),
            )

    assert load_analysis_job(db, job["id"])["config"] == {"settings": {"beam_size": 5}}


def test_cancellation_is_only_allowed_before_work_or_while_waiting(tmp_path: Path) -> None:
    first_video = tmp_path / "first.mp4"
    second_video = tmp_path / "second.mp4"
    first_video.write_bytes(b"first")
    second_video.write_bytes(b"second")
    db = tmp_path / "highlightminer.db"

    queued = create_analysis_job(db, _source(db, first_video), {"run": 1})
    assert cancel_analysis_job(db, queued["id"]) is True
    assert load_analysis_job(db, queued["id"])["status"] == "cancelled"

    running = create_analysis_job(db, _source(db, second_video), {"run": 2})
    start_analysis_job(db, running["id"])
    assert cancel_analysis_job(db, running["id"]) is False
    assert load_analysis_job(db, running["id"])["status"] == "running"

    mark_analysis_job_awaiting_input(db, running["id"], message="Choose a model")
    assert cancel_analysis_job(db, running["id"]) is True
    assert load_analysis_job(db, running["id"])["status"] == "cancelled"


def test_failures_and_recovery_are_terminal_and_observable(tmp_path: Path) -> None:
    first_video = tmp_path / "first.mp4"
    second_video = tmp_path / "second.mp4"
    first_video.write_bytes(b"first")
    second_video.write_bytes(b"second")
    db = tmp_path / "highlightminer.db"

    failed = create_analysis_job(db, _source(db, first_video), {"run": 1})
    start_analysis_job(db, failed["id"])
    assert fail_analysis_job(db, failed["id"], ValueError("bad media")) is True
    failed_row = load_analysis_job(db, failed["id"])
    assert failed_row["status"] == "failed"
    assert failed_row["error_type"] == "ValueError"
    assert list_analysis_job_events(db, failed["id"])[-1]["level"] == "error"

    interrupted = create_analysis_job(db, _source(db, second_video), {"run": 2})
    start_analysis_job(db, interrupted["id"])
    assert recover_interrupted_analysis_jobs(db, [interrupted["id"]]) == [interrupted["id"]]
    assert load_analysis_job(db, interrupted["id"])["status"] == "interrupted"
    assert list_analysis_job_events(db, interrupted["id"])[-1]["event"] == "job.interrupted"


def test_expired_heartbeat_recovery_preserves_live_running_jobs(tmp_path: Path) -> None:
    stale_video = tmp_path / "stale.mp4"
    live_video = tmp_path / "live.mp4"
    stale_video.write_bytes(b"stale")
    live_video.write_bytes(b"live")
    db = tmp_path / "highlightminer.db"
    stale = create_analysis_job(db, _source(db, stale_video), {"run": "stale"})
    live = create_analysis_job(db, _source(db, live_video), {"run": "live"})
    start_analysis_job(db, stale["id"])
    start_analysis_job(db, live["id"])

    heartbeat_analysis_job(
        db,
        stale["id"],
        now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    heartbeat_analysis_job(
        db,
        live["id"],
        now=datetime(2026, 1, 1, 12, 1, 30, tzinfo=timezone.utc),
    )

    recovered = recover_stale_analysis_jobs(
        db,
        now=datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc),
        stale_after_seconds=90.0,
    )

    assert recovered == [stale["id"]]
    assert load_analysis_job(db, stale["id"])["status"] == "interrupted"
    assert load_analysis_job(db, live["id"])["status"] == "running"
    event = list_analysis_job_events(db, stale["id"])[-1]
    assert event["event"] == "job.interrupted"
    assert event["details"]["reason"] == "heartbeat_expired"


def test_job_cannot_complete_with_an_analysis_from_another_source(tmp_path: Path) -> None:
    first_video = tmp_path / "first.mp4"
    second_video = tmp_path / "second.mp4"
    first_video.write_bytes(b"first")
    second_video.write_bytes(b"second")
    db = tmp_path / "highlightminer.db"
    first_source = _source(db, first_video)
    second_source = _source(db, second_video)
    job = create_analysis_job(db, first_source, {"run": 1})
    start_analysis_job(db, job["id"])
    wrong_analysis_id = _saved_analysis(db, second_video, second_source)

    with pytest.raises(ValueError, match="belongs to a different source"):
        complete_analysis_job(db, job["id"], wrong_analysis_id)

    assert load_analysis_job(db, job["id"])["status"] == "running"
