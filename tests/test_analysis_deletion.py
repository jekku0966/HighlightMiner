from __future__ import annotations

from pathlib import Path

import pytest

from highlightminer.analysis_history import (
    AnalysisDeletionBlocked,
    analysis_deletion_impact,
    delete_analysis,
)
from highlightminer.analysis_identity import load_analysis_identity, save_analysis_title
from highlightminer.analysis_jobs import create_analysis_job
from highlightminer.export_queue import enqueue_export_items, list_export_queue, start_export_batch
from highlightminer.identity import describe_source
from highlightminer.storage import (
    connect,
    learning_summary,
    list_analyses,
    load_analysis,
    load_review,
    record_export,
    register_source,
    save_analysis,
    save_review,
)


def _save(db: Path, video: Path, *, score: float = 0.9) -> str:
    return save_analysis(
        db,
        {
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
                    "score": score,
                    "peak_time": 42.0,
                    "start": 30.0,
                    "end": 60.0,
                    "audio_score": 0.8,
                    "transcript_score": 0.7,
                    "chat_score": 0.2,
                    "reason": "reaction",
                    "transcript": "wow",
                    "content_label": "Overwatch 2",
                }
            ],
        },
        transcript=[{"start": 40.0, "end": 41.0, "text": "wow", "score": 0.8}],
        audio_features=[{"time": 42.0, "dbfs": -10.0, "energy": 0.8, "onset": 0.5, "score": 0.7}],
        chat_features=[{"time": 42.0, "count": 3, "ratio": 1.5, "score": 0.4}],
        work_dir=video.parent,
        source=describe_source(video),
    )


def test_deletion_impact_reports_review_learning_export_and_queue_data(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video" * 1000)
    db = tmp_path / "highlightminer.db"
    analysis_id = _save(db, video)
    analysis = load_analysis(db, analysis_id)
    save_analysis_title(db, analysis_id, "Boss fight")
    review = load_review(db, analysis_id, analysis)
    review["items"]["H001"].update(status="keep", title="Clutch")
    save_review(db, analysis_id, review)
    output = tmp_path / "clips" / "Clutch.mp4"
    output.parent.mkdir()
    output.write_bytes(b"clip")
    record_export(db, analysis_id, "H001", output)
    enqueue_export_items(
        db,
        analysis,
        [{"candidate_id": "H001", "start": 30.0, "end": 60.0, "title": "Clutch"}],
        tmp_path / "clips",
    )

    impact = analysis_deletion_impact(db, analysis_id)

    assert impact == {
        "analysis_id": analysis_id,
        "analysis_title": "Boss fight",
        "video_name": "vod.mp4",
        "content_label": "Overwatch 2",
        "run_number": 1,
        "source_id": analysis["source_id"],
        "source_fingerprint": analysis["source_fingerprint"],
        "candidates": 1,
        "kept": 1,
        "rejected": 0,
        "unreviewed": 0,
        "review_events": 1,
        "exports": 1,
        "transcript_segments": 1,
        "audio_features": 1,
        "chat_features": 1,
        "queue_items": 1,
        "exporting_items": 0,
    }


def test_confirmed_deletion_cascades_database_state_but_keeps_exported_file(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video" * 1000)
    db = tmp_path / "highlightminer.db"
    analysis_id = _save(db, video)
    analysis = load_analysis(db, analysis_id)
    save_analysis_title(db, analysis_id, "Delete me")
    review = load_review(db, analysis_id, analysis)
    review["items"]["H001"]["status"] = "reject"
    save_review(db, analysis_id, review)
    output = tmp_path / "clips" / "H001.mp4"
    output.parent.mkdir()
    output.write_bytes(b"clip")
    record_export(db, analysis_id, "H001", output)
    enqueue_export_items(
        db,
        analysis,
        [{"candidate_id": "H001", "start": 30.0, "end": 60.0}],
        tmp_path / "clips",
    )

    deleted = delete_analysis(
        db,
        analysis_id,
        acknowledged=True,
        confirmed_analysis_id=analysis_id,
    )

    assert deleted["analysis_id"] == analysis_id
    assert list_analyses(db) == []
    assert list_export_queue(db) == []
    assert learning_summary(db) == {
        "total": 0,
        "kept": 0,
        "rejected": 0,
        "unreviewed": 0,
        "exported": 0,
    }
    assert output.exists()
    with pytest.raises(KeyError):
        load_analysis_identity(db, analysis_id)
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM metadata WHERE key = ?",
            (f"analysis_title:{analysis_id}",),
        ).fetchone()[0] == 0


def test_deletion_requires_confirmation_for_the_exact_analysis(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video" * 1000)
    db = tmp_path / "highlightminer.db"
    analysis_id = _save(db, video)

    with pytest.raises(ValueError, match="confirmation"):
        delete_analysis(
            db,
            analysis_id,
            acknowledged=True,
            confirmed_analysis_id="another-analysis",
        )

    assert load_analysis(db, analysis_id)["analysis_id"] == analysis_id


def test_deletion_requires_explicit_acknowledgement(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video" * 1000)
    db = tmp_path / "highlightminer.db"
    analysis_id = _save(db, video)

    with pytest.raises(ValueError, match="acknowledgement"):
        delete_analysis(
            db,
            analysis_id,
            acknowledged=False,
            confirmed_analysis_id=analysis_id,
        )

    assert load_analysis(db, analysis_id)["analysis_id"] == analysis_id


def test_deleting_one_vod_run_keeps_other_runs_and_never_reuses_run_number(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video" * 1000)
    db = tmp_path / "highlightminer.db"
    first = _save(db, video, score=0.9)
    second = _save(db, video, score=0.8)

    delete_analysis(db, second, acknowledged=True, confirmed_analysis_id=second)
    third = _save(db, video, score=0.7)

    assert load_analysis(db, first)["run_number"] == 1
    assert load_analysis(db, third)["run_number"] == 3
    assert [row["run_number"] for row in list_analyses(db)] == [3, 1]


def test_analysis_with_active_export_cannot_be_deleted(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video" * 1000)
    db = tmp_path / "highlightminer.db"
    analysis_id = _save(db, video)
    analysis = load_analysis(db, analysis_id)
    enqueue_export_items(
        db,
        analysis,
        [{"candidate_id": "H001", "start": 30.0, "end": 60.0}],
        tmp_path / "clips",
    )
    start_export_batch(db)

    with pytest.raises(AnalysisDeletionBlocked, match="active export"):
        delete_analysis(
            db,
            analysis_id,
            acknowledged=True,
            confirmed_analysis_id=analysis_id,
        )

    assert load_analysis(db, analysis_id)["analysis_id"] == analysis_id


def test_source_with_active_analysis_job_cannot_lose_history(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video" * 1000)
    db = tmp_path / "highlightminer.db"
    analysis_id = _save(db, video)
    source = register_source(db, describe_source(video))
    create_analysis_job(db, source, {"settings": {}, "video_path": str(video)})

    with pytest.raises(AnalysisDeletionBlocked, match="active analysis job"):
        delete_analysis(
            db,
            analysis_id,
            acknowledged=True,
            confirmed_analysis_id=analysis_id,
        )

    assert load_analysis(db, analysis_id)["analysis_id"] == analysis_id
