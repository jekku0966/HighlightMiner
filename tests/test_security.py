from pathlib import Path

import pytest

from highlightminer.config import Settings
from highlightminer.security import is_network_path, validate_local_video


def test_network_paths_are_detected() -> None:
    assert is_network_path(r"\\server\share\vod.mp4")
    assert is_network_path("//server/share/vod.mp4")


def test_local_video_validation(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"fake")
    assert validate_local_video(video) == video.resolve()

    wrong = tmp_path / "vod.exe"
    wrong.write_bytes(b"fake")
    with pytest.raises(ValueError):
        validate_local_video(wrong)


def test_custom_whisper_models_are_opt_in() -> None:
    with pytest.raises(ValueError):
        Settings(whisper_model="someone/custom-model")

    settings = Settings(
        whisper_model="someone/custom-model",
        allow_custom_whisper_model=True,
    )
    assert settings.whisper_model == "someone/custom-model"


def test_settings_ranges_are_validated() -> None:
    with pytest.raises(ValueError):
        Settings(max_candidates=100000)
    with pytest.raises(ValueError):
        Settings(min_candidate_score=-1)
