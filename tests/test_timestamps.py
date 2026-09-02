from __future__ import annotations

import pytest

from highlightminer import ui_mine
from highlightminer.timestamps import normalize_clip_bounds
from highlightminer.util import format_editable_time, format_time, parse_editable_time


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "00:00:00"),
        (12.0, "00:00:12"),
        (12.5, "00:00:12.5"),
        (12.05, "00:00:12.05"),
        (12.005, "00:00:12.005"),
        (62.25, "00:01:02.25"),
        (3661.001, "01:01:01.001"),
        (59.9996, "00:01:00"),
        (-1.0, "00:00:00"),
    ],
)
def test_display_timestamp_omits_only_redundant_fractional_zeroes(
    seconds: float,
    expected: str,
) -> None:
    assert format_time(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "00:00"),
        (12.5, "00:12.5"),
        (1434.5, "23:54.5"),
        (3918.0, "01:05:18"),
        (3964.5, "01:06:04.5"),
    ],
)
def test_editable_timestamp_uses_minutes_until_an_hour(
    seconds: float,
    expected: str,
) -> None:
    assert format_editable_time(seconds) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("23:54.5", 1434.5),
        ("01:05:18", 3918.0),
        ("01:06:04,5", 3964.5),
        ("3918.25", 3918.25),
        ("65:18", 3918.0),
    ],
)
def test_editable_timestamp_parser_accepts_supported_forms(
    value: str,
    expected: float,
) -> None:
    assert parse_editable_time(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-time",
        "-00:01",
        "00:60",
        "01:60:00",
        "00:00:60",
        "nan",
        "inf",
        f"{'9' * 400}:00:00",
    ],
)
def test_editable_timestamp_parser_rejects_invalid_values(value: str) -> None:
    assert parse_editable_time(value) is None


def test_clip_editor_untouched_values_preserve_exact_internal_boundaries() -> None:
    original_start = 1434.5004
    original_end = 1509.5004

    bounds = ui_mine._clip_editor_bounds(
        format_editable_time(original_start),
        format_editable_time(original_end),
        original_start=original_start,
        original_end=original_end,
        source_duration=2000.0,
    )

    assert bounds.start == original_start
    assert bounds.end == original_end


def test_clip_editor_parses_source_relative_hour_timestamps() -> None:
    bounds = ui_mine._clip_editor_bounds(
        "01:05:18",
        "01:06:04.5",
        original_start=0.0,
        original_end=1.0,
        source_duration=7200.0,
    )

    assert bounds.start == 3918.0
    assert bounds.end == 3964.5


def test_clip_editor_accepts_exact_minimum_duration() -> None:
    bounds = ui_mine._clip_editor_bounds(
        "00:10",
        "00:10.1",
        original_start=0.0,
        original_end=1.0,
        source_duration=100.0,
    )

    assert bounds.start == 10.0
    assert bounds.end == pytest.approx(10.1)


@pytest.mark.parametrize(
    ("start", "end", "duration"),
    [
        ("not-a-time", "00:10", 100.0),
        ("00:10", "00:10.05", 100.0),
        ("00:20", "00:10", 100.0),
        ("00:10", "02:00", 100.0),
    ],
)
def test_clip_editor_rejects_invalid_ranges(start: str, end: str, duration: float) -> None:
    with pytest.raises(ValueError, match="valid clip range"):
        ui_mine._clip_editor_bounds(
            start,
            end,
            original_start=10.0,
            original_end=20.0,
            source_duration=duration,
        )


def test_fractional_duration_overshoot_is_silently_clamped() -> None:
    duration = 15959.001859
    bounds = normalize_clip_bounds(15958.0, 15959.002, duration)

    assert bounds.start == 15958.0
    assert bounds.end == duration
    assert bounds.adjusted is True
    assert bounds.meaningfully_invalid is False


def test_meaningful_out_of_range_end_is_flagged() -> None:
    bounds = normalize_clip_bounds(10.0, 120.0, 100.0)

    assert bounds.start == 10.0
    assert bounds.end == 100.0
    assert bounds.meaningfully_invalid is True


def test_invalid_order_is_repaired_to_positive_range() -> None:
    bounds = normalize_clip_bounds(99.98, 99.0, 100.0)

    assert 0.0 <= bounds.start < bounds.end <= 100.0
    assert bounds.end - bounds.start == pytest.approx(0.1)
    assert bounds.meaningfully_invalid is True


def test_non_finite_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        normalize_clip_bounds(0.0, float("nan"), 100.0)
