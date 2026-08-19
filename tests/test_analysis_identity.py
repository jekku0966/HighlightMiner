from pathlib import Path

from highlightminer.analysis_identity import (
    analysis_name_from_settings,
    load_analysis_identities,
    load_analysis_identity,
    save_analysis_title,
)
from highlightminer.settings_presets import WEIGHT_PRESETS
from highlightminer.storage import save_analysis


def _save_run(db: Path, video: Path, weights: dict[str, float]) -> str:
    return save_analysis(
        db,
        {
            "version": 2,
            "video_path": str(video),
            "content_label": "Overwatch 2",
            "duration": 120.0,
            "media": {"duration": 120.0},
            "transcription": {"status": "available", "language": "en"},
            "chat": {"path": None, "messages": 0},
            "settings": {"weights": weights},
            "candidates": [],
        },
        transcript=[],
        audio_features=[],
        chat_features=[],
        work_dir=video.parent,
    )


def test_analysis_name_is_derived_from_stored_weight_snapshot() -> None:
    assert analysis_name_from_settings({"weights": WEIGHT_PRESETS["Balanced"]}) == "Balanced"
    assert analysis_name_from_settings({"weights": {"audio": 0.5, "transcript": 0.3, "chat": 0.2}}) == "Custom"
    assert analysis_name_from_settings({"max_candidates": 40}) == "Custom"


def test_existing_run_gets_name_without_rewriting_analysis(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"analysis identity" * 1000)
    db = tmp_path / "highlightminer.db"
    analysis_id = _save_run(db, video, WEIGHT_PRESETS["Audio-heavy"])

    identity = load_analysis_identity(db, analysis_id)
    assert identity == {"analysis_name": "Audio-heavy", "analysis_title": ""}


def test_optional_analysis_title_is_stored_separately(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"analysis title" * 1000)
    db = tmp_path / "highlightminer.db"
    first = _save_run(db, video, WEIGHT_PRESETS["Balanced"])
    second = _save_run(db, video, WEIGHT_PRESETS["Reaction-heavy"])

    assert save_analysis_title(db, second, "  Boss fight test  ") == "Boss fight test"
    identities = load_analysis_identities(db, [first, second])
    assert identities[first] == {"analysis_name": "Balanced", "analysis_title": ""}
    assert identities[second] == {"analysis_name": "Reaction-heavy", "analysis_title": "Boss fight test"}

    save_analysis_title(db, second, "")
    assert load_analysis_identity(db, second)["analysis_title"] == ""
