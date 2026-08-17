from pathlib import Path

from highlightminer.learning_store import learning_examples_with_context
from highlightminer.storage import save_analysis


def _analysis(video: Path, *, label: str, weights: dict[str, float], with_context: bool) -> dict:
    features = {
        "candidate_duration": 30.0,
        "peak_combined": 0.8,
        "top5_combined_mean": 0.7,
        "active_signal_count": 2,
        "has_chat": True,
        "seed_points": 6,
        "weight_audio": weights["audio"],
        "weight_transcript": weights["transcript"],
        "weight_chat": weights["chat"],
    }
    if with_context:
        features["context"] = {"content_label": label, "mining_profile": "Reaction-heavy"}
    return {
        "version": 2,
        "video_path": str(video),
        "content_label": label,
        "duration": 120.0,
        "media": {"duration": 120.0},
        "transcription": {"language": "en", "model": "large-v3"},
        "chat": {"path": None, "messages": 0},
        "settings": {"weights": weights},
        "candidates": [
            {
                "id": "H001",
                "rank": 1,
                "score": 0.8,
                "peak_time": 42.0,
                "start": 30.0,
                "end": 60.0,
                "audio_score": 0.7,
                "transcript_score": 0.8,
                "chat_score": 0.5,
                "reason": "combined signal spike",
                "transcript": "nice",
                "content_label": label,
                "features": features,
            }
        ],
    }


def test_learning_context_uses_saved_profile_and_reconstructs_older_runs(tmp_path: Path) -> None:
    db = tmp_path / "highlightminer.db"
    video_a = tmp_path / "a.mp4"
    video_b = tmp_path / "b.mp4"
    video_a.write_bytes(b"a")
    video_b.write_bytes(b"b")

    reaction_weights = {"audio": 0.20, "transcript": 0.60, "chat": 0.20}
    balanced_weights = {"audio": 0.34, "transcript": 0.42, "chat": 0.24}

    first = save_analysis(
        db,
        _analysis(video_a, label="Overwatch 2", weights=reaction_weights, with_context=True),
        transcript=[],
        audio_features=[],
        chat_features=[],
        work_dir=tmp_path,
        cache_info={"mining_profile": "Reaction-heavy"},
    )
    second = save_analysis(
        db,
        _analysis(video_b, label="Just Chatting", weights=balanced_weights, with_context=False),
        transcript=[],
        audio_features=[],
        chat_features=[],
        work_dir=tmp_path,
    )

    rows = learning_examples_with_context(db)
    by_analysis = {row["analysis_id"]: row for row in rows}

    assert by_analysis[first]["content_label"] == "Overwatch 2"
    assert by_analysis[first]["mining_profile"] == "Reaction-heavy"
    assert by_analysis[first]["mining_weights"] == reaction_weights

    assert by_analysis[second]["content_label"] == "Just Chatting"
    assert by_analysis[second]["mining_profile"] == "Balanced"
    assert by_analysis[second]["mining_weights"] == balanced_weights
