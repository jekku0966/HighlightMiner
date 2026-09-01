from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def ensure_dir(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


def format_time(seconds: float) -> str:
    """Format a media timestamp to milliseconds without redundant zeroes.

    This is presentation-only: callers retain the original numeric timestamp
    for review, preview, and export boundaries.
    """
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms == 1000:
        whole += 1
        ms = 0
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    fraction = f".{ms:03d}".rstrip("0") if ms else ""
    return f"{h:02d}:{m:02d}:{s:02d}{fraction}"


def format_editable_time(seconds: float) -> str:
    """Format an editable media timestamp without an unnecessary hour field."""
    label = format_time(seconds)
    return label[3:] if label.startswith("00:") else label


def parse_editable_time(value: Any) -> float | None:
    """Parse non-negative seconds, MM:SS, or HH:MM:SS media timestamps."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds if math.isfinite(seconds) and seconds >= 0.0 else None

    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
            return seconds if math.isfinite(seconds) and seconds >= 0.0 else None
        if len(parts) == 2:
            minutes_text, seconds_text = parts
            if not minutes_text.isdigit():
                return None
            minutes = int(minutes_text)
            seconds = float(seconds_text)
            if not math.isfinite(seconds) or not 0.0 <= seconds < 60.0:
                return None
            return minutes * 60.0 + seconds
        if len(parts) == 3:
            hours_text, minutes_text, seconds_text = parts
            if not hours_text.isdigit() or not minutes_text.isdigit():
                return None
            hours = int(hours_text)
            minutes = int(minutes_text)
            seconds = float(seconds_text)
            if minutes >= 60 or not math.isfinite(seconds) or not 0.0 <= seconds < 60.0:
                return None
            return hours * 3600.0 + minutes * 60.0 + seconds
    except ValueError:
        return None
    return None


def parse_time(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    parts = text.replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return None
    return None
