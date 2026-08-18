from __future__ import annotations

from pathlib import Path

from highlightminer import pipeline
from highlightminer.config import Settings
from highlightminer.model_access import PreparedModelReference


def test_pipeline_records_stage_timings_and_maps_transcription_progress(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"fake")
    captured: dict = {}
    progress_updates: list[tuple[str, float]] = []

    monkeypatch.setattr(pipeline, "validate_local_video", lambda path: Path(path))
    monkeypatch.setattr(pipeline, "ensure_dir", lambda path: Path(path))
    monkeypatch.setattr(pipeline, "load_model_access", lambda _db: object())
    monkeypatch.setattr(
        pipeline,
        "describe_source",
        lambda path: {
            "fingerprint": "source-fingerprint",
            "path": str(path),
            "video_name": Path(path).name,
            "file_size": 4,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "register_source",
        lambda _db, source: {
            "id": "source-id",
            "fingerprint": source["fingerprint"],
            "path": source["path"],
            "video_name": source["video_name"],
            "file_size": source["file_size"],
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
    monkeypatch.setattr(pipeline, "probe_media", lambda _video: {"duration": 100.0})
    monkeypatch.setattr(pipeline, "extract_analysis_audio", lambda _video, _wav: None)
    monkeypatch.setattr(pipeline, "analyze_audio", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        pipeline,
        "resolve_model_reference",
        lambda *_args, **_kwargs: PreparedModelReference(
            reference="large-v3",
            local_files_only=True,
            source="cache",
            display_name="large-v3",
        ),
    )

    def fake_transcribe(_wav, _settings, **kwargs):
        kwargs["progress"]("Transcribing — GPU (CUDA · FP16 · large-v3) · elapsed 00:00:02", 0.5)
        return (
            [{"start": 1.0, "end": 2.0, "text": "hello", "score": 0.0, "reasons": []}],
            {
                "status": "available",
                "language": "en",
                "device": "cuda",
                "compute_type": "float16",
                "model": "large-v3",
                "elapsed_seconds": 2.0,
                "audio_duration_seconds": 100.0,
                "real_time_factor": 0.02,
            },
        )

    monkeypatch.setattr(pipeline, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(pipeline, "find_candidates", lambda *_args, **_kwargs: [])

    if hasattr(pipeline, "prepare_preference_model"):
        def fail_learning(_db):
            raise RuntimeError("learner disabled in timing test")

        monkeypatch.setattr(pipeline, "prepare_preference_model", fail_learning)

    def fake_save_analysis(_db, analysis, _transcript, _audio, _chat, **kwargs):
        captured["analysis"] = analysis
        captured["cache_info"] = kwargs["cache_info"]
        return "analysis-id"

    monkeypatch.setattr(pipeline, "save_analysis", fake_save_analysis)

    analysis_id = pipeline.analyze_vod(
        video,
        tmp_path,
        Settings(device="auto", compute_type="auto"),
        progress=lambda message, value: progress_updates.append((message, value)),
        db_path=tmp_path / "highlightminer.db",
        reuse_features=False,
    )

    assert analysis_id == "analysis-id"
    assert any(
        message.startswith("Transcribing — GPU") and abs(value - 0.54) < 1e-9
        for message, value in progress_updates
    )

    timing = captured["cache_info"]["timings"]
    for key in (
        "source_setup_seconds",
        "media_probe_seconds",
        "audio_extract_seconds",
        "audio_analysis_seconds",
        "transcription_seconds",
        "candidate_ranking_seconds",
        "pipeline_elapsed_seconds",
    ):
        assert key in timing
        assert timing[key] >= 0.0

    transcription = captured["analysis"]["transcription"]
    assert transcription["device"] == "cuda"
    assert transcription["elapsed_seconds"] == 2.0
    assert transcription["real_time_factor"] == 0.02
