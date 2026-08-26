import pytest

from highlightminer import pipeline
from highlightminer.config import Settings
from highlightminer.model_access import ModelAccessPreferences
from highlightminer.transcribe import count_reaction_phrase_occurrences, score_text


def test_reaction_scores_above_plain_text():
    phrases = ["what the fuck", "no way"]
    plain, _ = score_text("I am walking over to the next room.", phrases)
    reaction, reasons = score_text("WHAT THE FUCK! No way! hahaha", phrases)
    assert reaction > plain
    assert reaction >= 0.7
    assert reasons


@pytest.mark.parametrize(
    ("text", "phrases", "expected"),
    [
        ("sorry", ["sorry"], 1),
        ("sorry sorry sorry", ["sorry"], 3),
        ("SORRY, Sorry! sorry?", ["sorry"], 3),
        ("nobody said no", ["no"], 1),
        ("No... WAY, that happened", ["no way"], 1),
        ("sorry sorry sorry", ["sorry sorry"], 2),
        ("sorry sorry sorry sorry", ["sorry sorry sorry sorry"], 1),
    ],
)
def test_reaction_occurrences_use_token_sequences(text: str, phrases: list[str], expected: int) -> None:
    assert count_reaction_phrase_occurrences(text, phrases) == expected


def test_duplicate_configured_phrases_do_not_inflate_occurrences() -> None:
    assert count_reaction_phrase_occurrences("sorry sorry", ["sorry", "SORRY!"]) == 2


def test_distinct_overlapping_configured_phrases_are_counted_deliberately() -> None:
    assert count_reaction_phrase_occurrences("ha ha ha", ["ha", "ha ha"]) == 5


def test_repetition_grows_with_diminishing_returns_and_does_not_max_score() -> None:
    scores = [score_text(" ".join(["sorry"] * count), ["sorry"])[0] for count in (1, 2, 3, 8)]

    assert scores[0] < scores[1] < scores[2] < scores[3]
    assert scores[3] < 1.0
    assert scores[3] - scores[2] < scores[1] - scores[0]


def test_changed_reaction_phrases_reuse_and_rescore_cached_transcript() -> None:
    access = ModelAccessPreferences(download_consent="deny")
    original = Settings(reaction_phrases=["sorry"])
    changed = Settings(reaction_phrases=["no way"])
    cached = [{"start": 0.0, "end": 2.0, "text": "sorry sorry", "score": 0.0, "reasons": []}]

    assert pipeline._stage_signatures(original, None, access) == pipeline._stage_signatures(changed, None, access)
    assert pipeline._rescore_transcript(cached, original)[0]["score"] > 0.0
    assert pipeline._rescore_transcript(cached, changed)[0]["score"] == 0.0


def test_changed_reaction_weight_does_not_invalidate_cached_transcript() -> None:
    access = ModelAccessPreferences(download_consent="deny")
    original = Settings(weights={"audio": 0.4, "transcript": 0.4, "chat": 0.2})
    changed = Settings(weights={"audio": 0.1, "transcript": 0.8, "chat": 0.1})

    original_signatures = pipeline._stage_signatures(original, None, access)
    changed_signatures = pipeline._stage_signatures(changed, None, access)

    assert original_signatures["transcript"] == changed_signatures["transcript"]
