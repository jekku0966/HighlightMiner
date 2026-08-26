from __future__ import annotations

from highlightminer.config import Settings
from highlightminer.scoring import deduplicate_candidates, find_candidates


def _candidate(
    name: str,
    start: float,
    end: float,
    peak: float,
    score: float,
    *,
    signals: int = 1,
) -> dict:
    return {
        "id": name,
        "start": start,
        "end": end,
        "peak_time": peak,
        "score": score,
        "features": {
            "active_signal_count": signals,
            "peak_combined": score,
        },
    }


def test_heavy_overlap_keeps_the_stronger_candidate() -> None:
    weaker = _candidate("weaker", 2.0, 29.0, 16.0, 0.72)
    stronger = _candidate("stronger", 0.0, 30.0, 15.0, 0.91)

    kept = deduplicate_candidates([weaker, stronger], max_candidates=10)

    assert [candidate["id"] for candidate in kept] == ["stronger"]
    assert kept[0]["features"]["duplicates_suppressed"] == 1


def test_partial_overlap_preserves_both_candidates() -> None:
    first = _candidate("first", 0.0, 20.0, 8.0, 0.90)
    second = _candidate("second", 12.0, 32.0, 24.0, 0.85)

    kept = deduplicate_candidates([first, second], max_candidates=10)

    assert {candidate["id"] for candidate in kept} == {"first", "second"}


def test_nearly_identical_candidates_collapse_to_one() -> None:
    first = _candidate("first", 20.0, 50.0, 34.0, 0.88)
    second = _candidate("second", 20.2, 49.8, 34.5, 0.86)

    kept = deduplicate_candidates([first, second], max_candidates=10)

    assert [candidate["id"] for candidate in kept] == ["first"]


def test_touching_adjacent_events_remain_distinct() -> None:
    first = _candidate("first", 0.0, 10.0, 5.0, 0.88)
    second = _candidate("second", 10.0, 20.0, 15.0, 0.86)

    kept = deduplicate_candidates([first, second], max_candidates=10)

    assert {candidate["id"] for candidate in kept} == {"first", "second"}


def test_heavily_overlapping_padding_does_not_hide_distinct_peaks() -> None:
    first = _candidate("first", 0.0, 30.0, 8.0, 0.90)
    second = _candidate("second", 5.0, 35.0, 25.0, 0.89)

    kept = deduplicate_candidates([first, second], max_candidates=10)

    assert {candidate["id"] for candidate in kept} == {"first", "second"}


def test_multiple_signal_candidates_for_one_event_collapse() -> None:
    audio = _candidate("audio", 40.0, 70.0, 55.0, 0.75)
    transcript = _candidate("transcript", 41.0, 69.0, 54.5, 0.79)
    combined = _candidate("combined", 39.0, 71.0, 55.2, 0.87, signals=3)

    kept = deduplicate_candidates([audio, transcript, combined], max_candidates=10)

    assert [candidate["id"] for candidate in kept] == ["combined"]
    assert kept[0]["features"]["duplicates_suppressed"] == 2


def test_strongest_candidate_wins_regardless_of_input_order() -> None:
    candidates = [
        _candidate("weak", 10.0, 40.0, 25.0, 0.60),
        _candidate("strong", 9.0, 41.0, 25.5, 0.95),
        _candidate("medium", 11.0, 39.0, 24.5, 0.80),
    ]

    kept = deduplicate_candidates(candidates, max_candidates=10)

    assert [candidate["id"] for candidate in kept] == ["strong"]


def test_duplicate_detection_handles_source_boundaries() -> None:
    candidates = [
        _candidate("start-strong", 0.0, 12.0, 1.0, 0.90),
        _candidate("start-weak", 0.0, 10.0, 1.5, 0.80),
        _candidate("end-strong", 88.0, 100.0, 99.0, 0.89),
        _candidate("end-weak", 90.0, 100.0, 98.5, 0.79),
    ]

    kept = deduplicate_candidates(candidates, max_candidates=10)

    assert [candidate["id"] for candidate in kept] == ["start-strong", "end-strong"]


def test_duplicate_accounting_continues_past_output_limit() -> None:
    candidates = [
        _candidate("strong", 10.0, 40.0, 25.0, 0.95),
        _candidate("medium", 11.0, 39.0, 24.5, 0.80),
        _candidate("weak", 9.0, 41.0, 25.5, 0.60),
    ]

    kept = deduplicate_candidates(candidates, max_candidates=1)

    assert [candidate["id"] for candidate in kept] == ["strong"]
    assert kept[0]["features"]["duplicates_suppressed"] == 2


def test_find_candidates_deduplicates_groups_just_beyond_merge_gap() -> None:
    settings = Settings(
        min_candidate_score=0.9,
        audio_window_sec=1.0,
        audio_hop_sec=1.0,
        pre_roll_sec=20.0,
        post_roll_sec=20.0,
        merge_gap_sec=10.0,
        weights={"audio": 1.0, "transcript": 0.0, "chat": 0.0},
        reaction_phrases=[],
    )
    audio = [
        {"time": float(second), "score": 1.0 if second in {30, 41} else 0.0}
        for second in range(80)
    ]

    kept = find_candidates(80.0, audio, [], [], settings, transcript_available=False)

    assert len(kept) == 1
    assert kept[0]["features"]["duplicates_suppressed"] == 1
