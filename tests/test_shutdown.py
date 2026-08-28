from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest

from highlightminer.analysis_jobs import (
    create_analysis_job,
    mark_analysis_job_awaiting_input,
    start_analysis_job,
)
from highlightminer.export_queue import start_export_batch
from highlightminer.shutdown import (
    ShutdownInProgressError,
    active_work_shutdown_block_reason,
    clear_shutdown_admission,
    request_shutdown_admission,
)
from highlightminer.storage import connect, register_source


def _source(db: Path, video: Path) -> dict:
    return register_source(
        db,
        {
            "id": "ignored",
            "fingerprint": f"fingerprint-{video.name}",
            "path": str(video),
            "video_name": video.name,
            "file_size": video.stat().st_size,
        },
    )


def test_shutdown_reservation_prevents_new_analysis_and_export_work(tmp_path: Path) -> None:
    db = tmp_path / "highlightminer.db"
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    source = _source(db, video)

    assert request_shutdown_admission(db) is None
    with pytest.raises(ShutdownInProgressError, match="shutting down"):
        create_analysis_job(db, source, {"run": 1})
    with pytest.raises(ShutdownInProgressError, match="shutting down"):
        start_export_batch(db)

    clear_shutdown_admission(db)
    assert create_analysis_job(db, source, {"run": 1})["status"] == "queued"


def test_active_work_wins_shutdown_race_but_model_choice_is_safe(tmp_path: Path) -> None:
    db = tmp_path / "highlightminer.db"
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    job = create_analysis_job(db, _source(db, video), {"run": 1})

    assert "Analysis is still" in active_work_shutdown_block_reason(db)
    assert "Analysis is still" in request_shutdown_admission(db)

    start_analysis_job(db, job["id"])
    mark_analysis_job_awaiting_input(db, job["id"], message="Choose a model")
    assert active_work_shutdown_block_reason(db) is None
    assert request_shutdown_admission(db) is None
    with pytest.raises(ShutdownInProgressError, match="shutting down"):
        start_analysis_job(db, job["id"])


def test_shutdown_and_analysis_start_are_admitted_atomically(tmp_path: Path) -> None:
    db = tmp_path / "highlightminer.db"
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    source = _source(db, video)
    ready = Barrier(2)

    def create_job() -> dict | ShutdownInProgressError:
        ready.wait()
        try:
            return create_analysis_job(db, source, {"run": 1})
        except ShutdownInProgressError as exc:
            return exc

    def request_shutdown() -> str | None:
        ready.wait()
        return request_shutdown_admission(db)

    with ThreadPoolExecutor(max_workers=2) as executor:
        job_result = executor.submit(create_job)
        shutdown_result = executor.submit(request_shutdown)

    job = job_result.result()
    reason = shutdown_result.result()
    if isinstance(job, ShutdownInProgressError):
        assert reason is None
    else:
        assert job["status"] == "queued"
        assert reason is not None and "Analysis is still" in reason


@pytest.mark.parametrize("offset", [timedelta(minutes=-5), timedelta(minutes=5)])
def test_stale_shutdown_reservation_does_not_block_future_work(
    tmp_path: Path,
    offset: timedelta,
) -> None:
    db = tmp_path / "highlightminer.db"
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    source = _source(db, video)
    stale = datetime.now(timezone.utc) + offset
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES ('ui_shutdown_admission', ?)",
            (stale.isoformat(timespec="seconds"),),
        )

    assert create_analysis_job(db, source, {"run": 1})["status"] == "queued"
