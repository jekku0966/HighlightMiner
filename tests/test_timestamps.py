from __future__ import annotations

import pytest

from highlightminer.timestamps import normalize_clip_bounds


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
