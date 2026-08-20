from highlightminer.config import Settings
from highlightminer.scoring import find_candidates


def test_candidate_created_around_spike():
    settings = Settings(
        min_candidate_score=0.35,
        pre_roll_sec=10,
        post_roll_sec=10,
        merge_gap_sec=3,
        reaction_phrases=[],
    )
    audio = [{"time": float(t), "score": 1.0 if t == 50 else 0.1} for t in range(100)]
    transcript = [{"start": 49.0, "end": 52.0, "text": "wow", "score": 0.9}]
    result = find_candidates(100, audio, transcript, [], settings)
    assert result
    assert result[0]["start"] <= 50 <= result[0]["end"]


def test_candidate_end_rounding_never_exceeds_source_duration():
    duration = 10.001859
    settings = Settings(
        min_candidate_score=0.8,
        pre_roll_sec=0,
        post_roll_sec=1,
        merge_gap_sec=1,
        reaction_phrases=[],
    )
    audio = [{"time": float(t), "score": 1.0 if t == 10 else 0.0} for t in range(11)]

    result = find_candidates(
        duration,
        audio,
        [],
        [],
        settings,
        transcript_available=False,
    )

    assert result
    assert result[0]["end"] == duration
    assert 0.0 <= result[0]["start"] < result[0]["end"] <= duration


def test_missing_transcript_renormalizes_available_signals():
    settings = Settings(
        min_candidate_score=0.5,
        pre_roll_sec=5,
        post_roll_sec=5,
        merge_gap_sec=2,
        weights={"audio": 0.34, "transcript": 0.42, "chat": 0.24},
        reaction_phrases=[],
    )
    audio = [{"time": float(t), "score": 0.9 if t == 20 else 0.0} for t in range(40)]
    chat = [{"time": float(t), "score": 0.9 if t == 20 else 0.0} for t in range(40)]

    result = find_candidates(
        40,
        audio,
        [],
        chat,
        settings,
        transcript_available=False,
    )

    assert result
    features = result[0]["features"]
    assert features["has_transcript"] is False
    assert features["weight_transcript"] == 0.0
    assert round(features["weight_audio"] + features["weight_chat"], 6) == 1.0


def test_audio_only_analysis_uses_full_available_weight():
    settings = Settings(
        min_candidate_score=0.8,
        weights={"audio": 0.34, "transcript": 0.42, "chat": 0.24},
        reaction_phrases=[],
    )
    audio = [{"time": float(t), "score": 1.0 if t == 10 else 0.0} for t in range(20)]

    result = find_candidates(
        20,
        audio,
        [],
        [],
        settings,
        transcript_available=False,
    )

    assert result
    assert result[0]["features"]["weight_audio"] == 1.0


def test_unavailable_preferred_signal_falls_back_to_existing_signals():
    settings = Settings(
        min_candidate_score=0.8,
        weights={"audio": 0.0, "transcript": 1.0, "chat": 0.0},
        reaction_phrases=[],
    )
    audio = [{"time": float(t), "score": 1.0 if t == 10 else 0.0} for t in range(20)]

    result = find_candidates(
        20,
        audio,
        [],
        [],
        settings,
        transcript_available=False,
    )

    assert result
    assert result[0]["features"]["weight_audio"] == 1.0
    assert result[0]["features"]["weight_transcript"] == 0.0