from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Settings
from .util import clamp, format_time


@dataclass
class TimelineSignal:
    time: float
    audio: float = 0.0
    transcript: float = 0.0
    chat: float = 0.0
    combined: float = 0.0


def _nearest_feature(features: list[dict], t: float, key: str = "score") -> float:
    if not features:
        return 0.0
    times = np.fromiter((float(x["time"]) for x in features), dtype=np.float64)
    idx = int(np.searchsorted(times, t))
    candidates = []
    if idx < len(features):
        candidates.append(idx)
    if idx > 0:
        candidates.append(idx - 1)
    best = min(candidates, key=lambda i: abs(float(features[i]["time"]) - t))
    return float(features[best].get(key, 0.0))


def _transcript_at(segments: list[dict], t: float) -> float:
    best = 0.0
    for seg in segments:
        if float(seg["start"]) - 0.5 <= t <= float(seg["end"]) + 0.5:
            best = max(best, float(seg.get("score", 0.0)))
    return best


def build_timeline(
    duration: float,
    audio_features: list[dict],
    transcript: list[dict],
    chat_features: list[dict],
    settings: Settings,
) -> list[TimelineSignal]:
    step = max(0.5, min(1.0, settings.audio_hop_sec))
    weights = settings.normalized_weights(bool(chat_features))
    timeline: list[TimelineSignal] = []
    t = 0.0
    while t <= duration:
        a = _nearest_feature(audio_features, t)
        tx = _transcript_at(transcript, t)
        ch = _nearest_feature(chat_features, t) if chat_features else 0.0
        combined = weights.get("audio", 0) * a + weights.get("transcript", 0) * tx + weights.get("chat", 0) * ch
        active_values = [a, tx] + ([ch] if chat_features else [])
        active = sum(v >= 0.68 for v in active_values)
        if active >= 2:
            combined += 0.10
        timeline.append(TimelineSignal(t, a, tx, ch, clamp(combined)))
        t += step
    return timeline


def _excerpt(transcript: list[dict], start: float, end: float, max_chars: int = 650) -> str:
    parts = [seg["text"] for seg in transcript if float(seg["end"]) >= start and float(seg["start"]) <= end]
    text = " ".join(x.strip() for x in parts if x.strip())
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


def find_candidates(
    duration: float,
    audio_features: list[dict],
    transcript: list[dict],
    chat_features: list[dict],
    settings: Settings,
) -> list[dict]:
    timeline = build_timeline(duration, audio_features, transcript, chat_features, settings)
    weights = settings.normalized_weights(bool(chat_features))
    seeds = [
        x for x in timeline
        if x.combined >= settings.min_candidate_score
        or x.audio >= 0.94
        or x.transcript >= 0.78
        or (chat_features and x.chat >= 0.92)
    ]
    if not seeds:
        return []

    groups: list[list[TimelineSignal]] = [[seeds[0]]]
    for point in seeds[1:]:
        if point.time - groups[-1][-1].time <= settings.merge_gap_sec:
            groups[-1].append(point)
        else:
            groups.append([point])

    candidates: list[dict] = []
    for group in groups:
        peak = max(group, key=lambda x: x.combined)
        raw_start = max(0.0, group[0].time - settings.pre_roll_sec)
        raw_end = min(duration, group[-1].time + settings.post_roll_sec)

        if raw_end - raw_start > settings.max_candidate_sec:
            start = max(0.0, peak.time - settings.pre_roll_sec)
            end = min(duration, start + settings.max_candidate_sec)
            if peak.time > end:
                end = min(duration, peak.time + settings.post_roll_sec)
                start = max(0.0, end - settings.max_candidate_sec)
        else:
            start, end = raw_start, raw_end

        local = [x for x in timeline if start <= x.time <= end]
        max_audio = max((x.audio for x in local), default=0.0)
        max_tx = max((x.transcript for x in local), default=0.0)
        max_chat = max((x.chat for x in local), default=0.0)
        avg_top = sorted((x.combined for x in local), reverse=True)[:5]
        top_mean = sum(avg_top) / max(1, len(avg_top))
        score = clamp(0.72 * peak.combined + 0.28 * top_mean)

        reasons = []
        if max_tx >= 0.55:
            reasons.append("reaction-heavy speech")
        if max_audio >= 0.72:
            reasons.append("audio spike")
        if chat_features and max_chat >= 0.70:
            reasons.append("chat burst")
        if not reasons:
            reasons.append("combined signal spike")

        signal_count = int(max_audio >= 0.68) + int(max_tx >= 0.68) + int(bool(chat_features) and max_chat >= 0.68)
        features = {
            "candidate_duration": round(end - start, 3),
            "peak_combined": round(float(peak.combined), 4),
            "top5_combined_mean": round(float(top_mean), 4),
            "active_signal_count": signal_count,
            "has_chat": bool(chat_features),
            "max_audio": round(max_audio, 4),
            "max_transcript": round(max_tx, 4),
            "max_chat": round(max_chat, 4),
            "weight_audio": round(float(weights.get("audio", 0.0)), 6),
            "weight_transcript": round(float(weights.get("transcript", 0.0)), 6),
            "weight_chat": round(float(weights.get("chat", 0.0)), 6),
            "seed_points": len(group),
        }

        candidates.append({
            "id": "",
            "rank": 0,
            "score": round(score, 4),
            "peak_time": round(peak.time, 3),
            "start": round(start, 3),
            "end": round(end, 3),
            "start_label": format_time(start),
            "end_label": format_time(end),
            "audio_score": round(max_audio, 4),
            "transcript_score": round(max_tx, 4),
            "chat_score": round(max_chat, 4),
            "reason": ", ".join(reasons),
            "transcript": _excerpt(transcript, start, end),
            "features": features,
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    kept: list[dict] = []
    for cand in candidates:
        overlap = False
        for prev in kept:
            intersection = max(0.0, min(cand["end"], prev["end"]) - max(cand["start"], prev["start"]))
            smaller = min(cand["end"] - cand["start"], prev["end"] - prev["start"])
            if smaller > 0 and intersection / smaller >= 0.65:
                overlap = True
                break
        if not overlap:
            kept.append(cand)
        if len(kept) >= settings.max_candidates:
            break

    for rank, cand in enumerate(kept, start=1):
        cand["rank"] = rank
        cand["id"] = f"H{rank:03d}"
    return kept
