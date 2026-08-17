from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .security import MAX_JSON_LINE_BYTES, MAX_JSON_NESTING, validate_chat_file
from .util import parse_time

# Parser is an original permissive implementation for common chat-export shapes.
# TwitchDownloader is compatibility context only; no TwitchDownloader code is used.

_TIME_KEYS = (
    "content_offset_seconds", "offset_seconds", "timestamp_seconds", "seconds",
    "timestamp", "time", "offset", "video_offset",
)
_TEXT_KEYS = ("body", "message", "text", "content")


def _message_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in _TEXT_KEYS:
            if key in value:
                found = _message_text(value[key])
                if found:
                    return found
        fragments = value.get("fragments")
        if isinstance(fragments, list):
            return "".join(_message_text(x) for x in fragments).strip()
    if isinstance(value, list):
        return " ".join(filter(None, (_message_text(x) for x in value))).strip()
    return ""


def _record_from_dict(d: dict) -> dict | None:
    t = None
    for key in _TIME_KEYS:
        if key in d:
            t = parse_time(d[key])
            if t is not None:
                break
    if t is None:
        return None

    text = ""
    for key in _TEXT_KEYS:
        if key in d:
            text = _message_text(d[key])
            if text:
                break
    if not text and isinstance(d.get("message"), dict):
        text = _message_text(d["message"])
    return {"time": t, "text": text} if text else None


def _walk_json(obj: Any, depth: int = 0) -> Iterable[dict]:
    if depth > MAX_JSON_NESTING:
        raise ValueError(f"Chat JSON nesting exceeds the safety limit ({MAX_JSON_NESTING}).")
    if isinstance(obj, dict):
        rec = _record_from_dict(obj)
        if rec:
            yield rec
        for value in obj.values():
            if isinstance(value, (dict, list)):
                yield from _walk_json(value, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_json(item, depth + 1)


def load_chat(path: str | Path) -> list[dict]:
    p = validate_chat_file(path)
    suffix = p.suffix.lower()
    records: list[dict] = []

    if suffix == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                rec = _record_from_dict(row)
                if rec:
                    records.append(rec)
    elif suffix in {".jsonl", ".ndjson"}:
        with p.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                if len(line) > MAX_JSON_LINE_BYTES:
                    raise ValueError(
                        f"Chat JSON line {line_no} exceeds the safety limit ({MAX_JSON_LINE_BYTES:,} characters)."
                    )
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                records.extend(_walk_json(obj))
    else:
        with p.open("r", encoding="utf-8") as f:
            records.extend(_walk_json(json.load(f)))

    # Recursive JSON parsing can encounter wrapper + nested records. De-dupe exact matches.
    dedup = {(round(float(r["time"]), 3), r["text"]): r for r in records if r["time"] >= 0}
    return sorted(dedup.values(), key=lambda r: r["time"])


def analyze_chat(records: list[dict], duration: float, bucket_sec: float = 1.0) -> list[dict]:
    if not records:
        return []
    bucket_sec = max(0.25, float(bucket_sec))
    n = max(1, int(np.ceil(duration / bucket_sec)))
    counts = np.zeros(n, dtype=np.float32)
    for r in records:
        idx = int(float(r["time"]) // bucket_sec)
        if 0 <= idx < n:
            counts[idx] += 1.0

    # Compare each second against a local ~60s baseline. +1 keeps quiet chats sane.
    window = max(3, int(round(60.0 / bucket_sec)))
    kernel = np.ones(window, dtype=np.float32) / window
    left = window // 2
    right = window - 1 - left
    padded = np.pad(counts, (left, right), mode="edge")
    baseline = np.convolve(padded, kernel, mode="valid")
    ratio = (counts + 1.0) / (baseline + 1.0)
    p50 = float(np.percentile(ratio, 50))
    p97 = float(np.percentile(ratio, 97))
    span = max(1e-6, p97 - p50)
    score = np.clip((ratio - p50) / span, 0.0, 1.0)

    return [
        {
            "time": round((i + 0.5) * bucket_sec, 3),
            "count": int(counts[i]),
            "ratio": round(float(ratio[i]), 3),
            "score": round(float(score[i]), 4),
        }
        for i in range(n)
    ]
