from __future__ import annotations

import math
from dataclasses import dataclass

_BOUNDARY_TOLERANCE_SEC = 0.01
_MIN_POSITIVE_DURATION_SEC = 1e-6


@dataclass(frozen=True)
class ClipBounds:
    start: float
    end: float
    adjusted: bool
    meaningfully_invalid: bool


def normalize_clip_bounds(
    start: float,
    end: float,
    source_duration: float,
    *,
    min_duration: float = 0.1,
    tolerance: float = _BOUNDARY_TOLERANCE_SEC,
) -> ClipBounds:
    """Return finite clip bounds constrained to a source timeline.

    Tiny boundary differences, such as a millisecond-rounded candidate ending a
    fraction above ffprobe's source duration, are silently clamped. Larger or
    structurally invalid ranges are marked so callers can warn/log if useful.
    """
    raw_start = float(start)
    raw_end = float(end)
    duration = float(source_duration)
    minimum = float(min_duration)
    raw_tolerance = float(tolerance)

    if not all(math.isfinite(value) for value in (raw_start, raw_end, duration, minimum, raw_tolerance)):
        raise ValueError("Clip timestamps and source duration must be finite numbers.")
    if duration <= 0.0:
        raise ValueError("Source duration must be greater than zero.")

    tolerance = max(0.0, raw_tolerance)
    minimum = min(duration, max(_MIN_POSITIVE_DURATION_SEC, minimum))
    meaningfully_invalid = (
        raw_start < -tolerance
        or raw_end > duration + tolerance
        or raw_start >= duration
        or raw_end <= raw_start
    )

    normalized_start = min(duration, max(0.0, raw_start))
    normalized_end = min(duration, max(0.0, raw_end))

    if normalized_end <= normalized_start or normalized_end - normalized_start < minimum:
        if normalized_start + minimum <= duration:
            normalized_end = normalized_start + minimum
        else:
            normalized_end = duration
            normalized_start = max(0.0, duration - minimum)

    adjusted = not (
        math.isclose(normalized_start, raw_start, rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(normalized_end, raw_end, rel_tol=0.0, abs_tol=1e-12)
    )
    return ClipBounds(
        start=normalized_start,
        end=normalized_end,
        adjusted=adjusted,
        meaningfully_invalid=meaningfully_invalid,
    )
