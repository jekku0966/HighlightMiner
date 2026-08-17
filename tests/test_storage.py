from pathlib import Path

from highlightminer.storage import (
    list_analyses,
    load_analysis,
    load_review,
    record_export,
    save_analysis,
    save_review,
    transcript_window,
)


def _sample_analysis(video: Path) -> dict:
    return {
        "version": 2,
        "video_path": str(video),
        "content_label": "Overwatch 2",
        "duration": 120.0,
        "media": {"duration": 120.0},
        "transcription": {"language": "en", "model": "large-v3"},
        "chat": {"path": None, "messages": 0},
        "settings": {"max_candidates": 40},
        "candidates": [
            {
                "id": "H001",
                "rank": 1,
                "score": 0.91,
                "peak_time": 42.0,
                "start": 30.0,
                "end": 60.0,
                "audio_score": 0.88,
                "transcript_score": 0.76,
                "chat_score": 0.22,
                "reason": "audio spike, reaction-heavy speech",
                "transcript": "what the fuck",
                "content_label": "Overwatch 2",
            }
        ],
    }


def test_database_round_trip(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"fake")
    db = tmp_path / "highlightminer.db"
    analysis = _sample_analysis(video)

    analysis_id = save_analysis(
        db,
        analysis,
        transcript=[{"start": 40.0, "end": 43.0, "text": "what the fuck", "score": 0.8, "reasons": ["reaction phrase"]}],
        audio_features=[{"time": 42.0, "dbfs": -10.0, "energy": 0.8, "onset": 0.6, "score": 0.75}],
        chat_features=[{"time": 42.5, "count": 5, "ratio": 2.0, "score": 0.4}],
        work_dir=tmp_path,
    )

    loaded = load_analysis(db, analysis_id)
    assert loaded["content_label"] == "Overwatch 2"
    assert loaded["candidates"][0]["id"] == "H001"
    assert loaded["candidates"][0]["audio_score"] == 0.88

    review = load_review(db, analysis_id, loaded)
    review["items"]["H001"].update(status="keep", start=31.0, end=58.0, title="Clutch")
    save_review(db, analysis_id, review)

    updated = load_review(db, analysis_id, loaded)
    assert updated["items"]["H001"]["status"] == "keep"
    assert updated["items"]["H001"]["title"] == "Clutch"
    assert updated["items"]["H001"]["start"] == 31.0

    export = tmp_path / "clips" / "Overwatch 2" / "H001.mp4"
    export.parent.mkdir(parents=True)
    export.write_bytes(b"clip")
    record_export(db, analysis_id, "H001", export)
    exported_review = load_review(db, analysis_id, loaded)
    assert exported_review["items"]["H001"]["export_path"] == str(export.resolve())
    assert exported_review["items"]["H001"]["exported_at"]

    history = list_analyses(db)
    assert history[0]["id"] == analysis_id
    assert history[0]["kept"] == 1

    transcript = transcript_window(db, analysis_id, 39.0, 44.0)
    assert transcript[0]["text"] == "what the fuck"
