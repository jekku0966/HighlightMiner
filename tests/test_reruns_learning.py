from pathlib import Path

from highlightminer.identity import describe_source
from highlightminer.storage import (
    find_source_runs,
    learning_examples,
    learning_summary,
    load_analysis,
    load_reusable_features,
    load_review,
    save_analysis,
    save_review,
)


def _analysis(video: Path, score: float = 0.91) -> dict:
    return {
        "version": 2,
        "video_path": str(video),
        "content_label": "Overwatch 2",
        "duration": 120.0,
        "media": {"duration": 120.0},
        "transcription": {"language": "en", "model": "large-v3"},
        "chat": {"path": None, "messages": 0},
        "settings": {"max_candidates": 40},
        "candidates": [{
            "id": "H001", "rank": 1, "score": score, "peak_time": 42.0,
            "start": 30.0, "end": 60.0, "audio_score": 0.88,
            "transcript_score": 0.76, "chat_score": 0.22,
            "reason": "audio spike, reaction-heavy speech",
            "transcript": "what the fuck", "content_label": "Overwatch 2",
            "features": {"active_signal_count": 2, "candidate_duration": 30.0},
        }],
    }


def _save(db: Path, video: Path, score: float = 0.91) -> str:
    return save_analysis(
        db,
        _analysis(video, score),
        transcript=[{"start": 40.0, "end": 43.0, "text": "what the fuck", "score": 0.8, "reasons": ["reaction phrase"]}],
        audio_features=[{"time": 42.0, "dbfs": -10.0, "energy": 0.8, "onset": 0.6, "score": 0.75}],
        chat_features=[{"time": 42.5, "count": 5, "ratio": 2.0, "score": 0.4}],
        work_dir=video.parent,
        source=describe_source(video),
        signatures={"audio": "audio-a", "transcript": "tx-a", "chat": "chat-a"},
    )


def test_same_vod_gets_multiple_runs_and_reusable_stages(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"same vod" * 10000)
    db = tmp_path / "highlightminer.db"

    first = _save(db, video)
    second = _save(db, video, score=0.77)
    assert load_analysis(db, first)["run_number"] == 1
    assert load_analysis(db, second)["run_number"] == 2

    source, runs = find_source_runs(db, video)
    assert len(runs) == 2
    cache = load_reusable_features(
        db,
        source["id"],
        audio_signature="audio-a",
        transcript_signature="tx-a",
        chat_signature="chat-a",
    )
    assert cache["audio"][0]["score"] == 0.75
    assert cache["transcript"][0]["text"] == "what the fuck"
    assert cache["chat"][0]["count"] == 5


def test_skipped_transcript_run_does_not_shadow_older_valid_cache(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"cache guard" * 10000)
    db = tmp_path / "highlightminer.db"

    _save(db, video)
    skipped = _analysis(video, score=0.70)
    skipped["transcription"] = {
        "status": "skipped",
        "reason": "model_downloads_disabled",
        "model": "large-v3",
    }
    save_analysis(
        db,
        skipped,
        transcript=[],
        audio_features=[{"time": 42.0, "dbfs": -11.0, "energy": 0.7, "onset": 0.5, "score": 0.70}],
        chat_features=[{"time": 42.5, "count": 4, "ratio": 1.8, "score": 0.35}],
        work_dir=video.parent,
        source=describe_source(video),
        signatures={"audio": "audio-a", "transcript": None, "chat": "chat-a"},
    )

    source, _runs = find_source_runs(db, video)
    cache = load_reusable_features(
        db,
        source["id"],
        audio_signature="audio-a",
        transcript_signature="tx-a",
        chat_signature="chat-a",
    )

    assert cache["transcript"][0]["text"] == "what the fuck"


def test_learning_keeps_unreviewed_as_unlabeled(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"learning" * 1000)
    db = tmp_path / "highlightminer.db"
    analysis_id = _save(db, video)

    example = learning_examples(db)[0]
    assert example["review_status"] == "unreviewed"
    assert example["label"] is None
    assert example["features"]["active_signal_count"] == 2

    analysis = load_analysis(db, analysis_id)
    review = load_review(db, analysis_id, analysis)
    review["items"]["H001"]["status"] = "reject"
    save_review(db, analysis_id, review)

    example = learning_examples(db, include_unreviewed=False)[0]
    assert example["label"] == 0
    assert example["review_event_count"] == 1
    assert learning_summary(db)["rejected"] == 1
