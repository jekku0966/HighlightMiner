from __future__ import annotations

from pathlib import Path

import pytest

from highlightminer import pipeline
from highlightminer.analysis_jobs import (
    AnalysisJobStateError,
    AnalysisJobTerminalError,
    cancel_analysis_job,
    create_analysis_job,
    interrupt_analysis_job,
    list_analysis_job_events,
    load_analysis_job,
    start_analysis_job,
)
from highlightminer.config import Settings
from highlightminer.model_access import ModelAccessPreferences, ModelDecisionRequired
from highlightminer.storage import connect, load_analysis, register_source


def _stub_pipeline(monkeypatch, *, probe_error: Exception | None = None) -> None:
    monkeypatch.setattr(pipeline, "validate_local_video", lambda path: Path(path))
    monkeypatch.setattr(pipeline, "ensure_dir", lambda path: Path(path))
    monkeypatch.setattr(
        pipeline,
        "load_model_access",
        lambda _db: ModelAccessPreferences(download_consent="unset"),
    )
    monkeypatch.setattr(
        pipeline,
        "describe_source",
        lambda path: {
            "fingerprint": "source-fingerprint",
            "path": str(path),
            "video_name": Path(path).name,
            "file_size": Path(path).stat().st_size,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_stage_signatures",
        lambda *_args, **_kwargs: {"audio": "a", "transcript": "t", "chat": "c"},
    )
    monkeypatch.setattr(
        pipeline,
        "load_reusable_features",
        lambda *_args, **_kwargs: {
            "audio": None,
            "transcript": None,
            "transcription": None,
            "chat": None,
            "chat_info": None,
            "from": {},
        },
    )
    if probe_error is None:
        monkeypatch.setattr(pipeline, "probe_media", lambda _video: {"duration": 10.0})
    else:
        def fail_probe(_video):
            raise probe_error

        monkeypatch.setattr(pipeline, "probe_media", fail_probe)
    monkeypatch.setattr(pipeline, "extract_analysis_audio", lambda _video, _wav: None)
    monkeypatch.setattr(pipeline, "analyze_audio", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(pipeline, "find_candidates", lambda *_args, **_kwargs: [])


def test_model_decision_resumes_same_job_with_original_settings_snapshot(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch)

    def require_decision(*_args, **_kwargs):
        raise ModelDecisionRequired("Choose how to handle the missing model")

    monkeypatch.setattr(pipeline, "resolve_model_reference", require_decision)

    with pytest.raises(ModelDecisionRequired) as raised:
        pipeline.analyze_vod(
            video,
            tmp_path,
            Settings(beam_size=5),
            db_path=db,
            reuse_features=False,
        )

    job_id = str(raised.value.analysis_job_id)
    waiting = load_analysis_job(db, job_id)
    assert waiting["status"] == "awaiting_input"
    assert waiting["config"]["settings"]["beam_size"] == 5
    assert waiting["config"]["processing_mode"] == pipeline.FORCE_FULL_REPROCESS

    analysis_id = pipeline.analyze_vod(
        video,
        tmp_path,
        Settings(beam_size=1),
        db_path=db,
        reuse_features=True,
        skip_transcription=True,
        analysis_job_id=job_id,
    )

    completed = load_analysis_job(db, job_id)
    analysis = load_analysis(db, analysis_id)
    assert completed["status"] == "completed"
    assert completed["analysis_id"] == analysis_id
    assert analysis["settings"]["beam_size"] == 5
    assert analysis["cache"]["reuse_enabled"] is False
    assert analysis["cache"]["processing_mode"] == pipeline.FORCE_FULL_REPROCESS

    events = list_analysis_job_events(db, job_id)
    event_names = [event["event"] for event in events]
    assert "model.input_required" in event_names
    assert "transcription.skip_requested" in event_names
    assert "transcription.skipped" in event_names
    assert event_names[-1] == "job.completed"


def test_cancelled_model_decision_asks_again_when_download_policy_is_unset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch)

    def require_decision(*_args, **_kwargs):
        raise ModelDecisionRequired("Choose how to handle the missing model")

    monkeypatch.setattr(pipeline, "resolve_model_reference", require_decision)

    with pytest.raises(ModelDecisionRequired) as first:
        pipeline.analyze_vod(video, tmp_path, Settings(), db_path=db)

    assert cancel_analysis_job(db, str(first.value.analysis_job_id)) is True

    with pytest.raises(ModelDecisionRequired) as second:
        pipeline.analyze_vod(video, tmp_path, Settings(), db_path=db)

    assert second.value.analysis_job_id != first.value.analysis_job_id


def test_force_full_reprocess_never_reads_prior_evidence(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "load_reusable_features",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("full reprocess read prior evidence")
        ),
    )

    analysis_id = pipeline.analyze_vod(
        video,
        tmp_path,
        Settings(),
        db_path=db,
        reuse_features=False,
        skip_transcription=True,
    )

    analysis = load_analysis(db, analysis_id)
    assert analysis["cache"]["processing_mode"] == pipeline.FORCE_FULL_REPROCESS
    assert analysis["cache"]["reused_stages"] == []


def test_pipeline_failure_marks_job_failed_with_error_event(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch, probe_error=ValueError("invalid duration metadata"))

    with pytest.raises(ValueError, match="invalid duration metadata"):
        pipeline.analyze_vod(
            video,
            tmp_path,
            Settings(),
            db_path=db,
            reuse_features=False,
        )

    with connect(db) as conn:
        job_id = str(conn.execute("SELECT id FROM analysis_jobs").fetchone()[0])
    failed = load_analysis_job(db, job_id)
    assert failed["status"] == "failed"
    assert failed["error_type"] == "ValueError"
    assert failed["error_message"] == "invalid duration metadata"
    assert failed["timings"]["pipeline_elapsed_seconds"] >= 0.0
    assert list_analysis_job_events(db, job_id)[-1]["event"] == "job.failed"


def test_duplicate_caller_cannot_fail_an_existing_running_job(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch)
    settings = Settings()
    source = register_source(
        db,
        {
            "fingerprint": "source-fingerprint",
            "path": str(video),
            "video_name": video.name,
            "file_size": video.stat().st_size,
        },
    )
    config = pipeline.snapshot_analysis_config(
        video=video,
        work=tmp_path,
        settings=settings,
        chat_path=None,
        content_label="Other",
        source_fingerprint="source-fingerprint",
        reuse_features=False,
        transcription_requested=True,
    )
    job = create_analysis_job(db, source, config)
    start_analysis_job(db, job["id"])

    with pytest.raises(AnalysisJobStateError, match="while it is running"):
        pipeline.analyze_vod(
            video,
            tmp_path,
            Settings(beam_size=1),
            db_path=db,
            analysis_job_id=job["id"],
        )

    assert load_analysis_job(db, job["id"])["status"] == "running"


def test_precreated_job_fails_cleanly_if_startup_validation_fails(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    missing_video = tmp_path / "missing.mp4"
    db = tmp_path / "highlightminer.db"
    source = register_source(
        db,
        {
            "fingerprint": "source-fingerprint",
            "path": str(video),
            "video_name": video.name,
            "file_size": video.stat().st_size,
        },
    )
    config = pipeline.snapshot_analysis_config(
        video=missing_video,
        work=tmp_path,
        settings=Settings(),
        chat_path=None,
        content_label="Other",
        source_fingerprint="source-fingerprint",
        reuse_features=True,
        transcription_requested=True,
    )
    job = create_analysis_job(db, source, config)

    with pytest.raises(FileNotFoundError):
        pipeline.analyze_vod(
            missing_video,
            tmp_path,
            Settings(),
            db_path=db,
            analysis_job_id=job["id"],
        )

    failed = load_analysis_job(db, job["id"])
    assert failed["status"] == "failed"
    assert failed["error_type"] == "FileNotFoundError"


def test_resume_preserves_snapshot_that_disabled_transcription(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "resolve_model_reference",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("model resolution must remain disabled")
        ),
    )
    source = register_source(
        db,
        {
            "fingerprint": "source-fingerprint",
            "path": str(video),
            "video_name": video.name,
            "file_size": video.stat().st_size,
        },
    )
    config = pipeline.snapshot_analysis_config(
        video=video,
        work=tmp_path,
        settings=Settings(),
        chat_path=None,
        content_label="Other",
        source_fingerprint="source-fingerprint",
        reuse_features=False,
        transcription_requested=False,
    )
    job = create_analysis_job(db, source, config)

    pipeline.analyze_vod(
        video,
        tmp_path,
        Settings(),
        db_path=db,
        analysis_job_id=job["id"],
        skip_transcription=False,
    )

    completed = load_analysis_job(db, job["id"])
    assert completed["status"] == "completed"
    events = [event["event"] for event in list_analysis_job_events(db, job["id"])]
    assert "transcription.skip_requested" in events
    assert "transcription.skipped" in events


def test_model_decision_race_preserves_concurrent_terminal_state(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "resolve_model_reference",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ModelDecisionRequired("Choose how to continue")
        ),
    )
    real_mark_awaiting = pipeline.mark_analysis_job_awaiting_input

    def interrupt_before_awaiting(db_path, job_id, *, message):
        interrupt_analysis_job(db_path, job_id, message="Worker ownership was lost")
        return real_mark_awaiting(db_path, job_id, message=message)

    monkeypatch.setattr(
        pipeline,
        "mark_analysis_job_awaiting_input",
        interrupt_before_awaiting,
    )

    with pytest.raises(AnalysisJobTerminalError) as raised:
        pipeline.analyze_vod(
            video,
            tmp_path,
            Settings(),
            db_path=db,
            reuse_features=False,
        )

    assert raised.value.job["status"] == "interrupted"
    assert load_analysis_job(db, raised.value.job["id"])["status"] == "interrupted"
    assert list_analysis_job_events(db, raised.value.job["id"])[-1]["event"] == "job.interrupted"


def test_finalization_race_rolls_back_unlinked_analysis(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch)
    real_save_analysis = pipeline.save_analysis

    def interrupt_then_save(db_path, *args, **kwargs):
        with connect(db_path) as inspection:
            job_id = str(inspection.execute("SELECT id FROM analysis_jobs").fetchone()[0])
        assert interrupt_analysis_job(
            db_path,
            job_id,
            message="Worker lease expired during finalization",
        ) is True
        return real_save_analysis(db_path, *args, **kwargs)

    monkeypatch.setattr(pipeline, "save_analysis", interrupt_then_save)

    with pytest.raises(AnalysisJobTerminalError) as raised:
        pipeline.analyze_vod(
            video,
            tmp_path,
            Settings(),
            db_path=db,
            reuse_features=False,
            skip_transcription=True,
        )

    assert raised.value.job["status"] == "interrupted"
    assert raised.value.job["analysis_id"] is None
    with connect(db) as inspection:
        assert inspection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0


def test_completion_callback_failure_does_not_reclassify_success(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch)

    def progress(_message: str, value: float) -> None:
        if value == 1.0:
            raise RuntimeError("status widget disappeared")

    analysis_id = pipeline.analyze_vod(
        video,
        tmp_path,
        Settings(),
        progress=progress,
        db_path=db,
        reuse_features=False,
        skip_transcription=True,
    )

    with connect(db) as inspection:
        job_id = str(inspection.execute("SELECT id FROM analysis_jobs").fetchone()[0])
    completed = load_analysis_job(db, job_id)
    assert completed["status"] == "completed"
    assert completed["analysis_id"] == analysis_id


def test_concurrent_terminal_state_wins_over_stale_worker_error(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    _stub_pipeline(monkeypatch, probe_error=ValueError("stale worker failure"))
    real_fail_job = pipeline.fail_analysis_job

    def interrupt_before_failure(db_path, job_id, error, *, timings):
        assert interrupt_analysis_job(
            db_path,
            job_id,
            message="Another worker already recovered this job",
        ) is True
        return real_fail_job(db_path, job_id, error, timings=timings)

    monkeypatch.setattr(pipeline, "fail_analysis_job", interrupt_before_failure)

    with pytest.raises(AnalysisJobTerminalError) as raised:
        pipeline.analyze_vod(
            video,
            tmp_path,
            Settings(),
            db_path=db,
            reuse_features=False,
        )

    assert raised.value.job["status"] == "interrupted"
    assert load_analysis_job(db, raised.value.job["id"])["status"] == "interrupted"
