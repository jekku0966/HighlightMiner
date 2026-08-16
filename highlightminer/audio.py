from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

from .util import clamp


def _robust_scale(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    p50 = float(np.percentile(values, 50))
    p95 = float(np.percentile(values, 95))
    span = max(1e-6, p95 - p50)
    return np.clip((values - p50) / span, 0.0, 1.0)


def analyze_audio(wav_path: str | Path, window_sec: float = 1.0, hop_sec: float = 0.5) -> list[dict]:
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError("Expected 16-bit PCM WAV from FFmpeg")
        channels = wf.getnchannels()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    win = max(1, int(window_sec * rate))
    hop = max(1, int(hop_sec * rate))
    times: list[float] = []
    db_values: list[float] = []

    for start in range(0, max(1, len(samples) - win + 1), hop):
        chunk = samples[start:start + win]
        if chunk.size == 0:
            break
        rms = float(np.sqrt(np.mean(np.square(chunk), dtype=np.float64)))
        dbfs = 20.0 * math.log10(max(rms, 1e-7))
        times.append((start + chunk.size / 2) / rate)
        db_values.append(dbfs)

    db = np.asarray(db_values, dtype=np.float32)
    energy = _robust_scale(db)
    delta = np.maximum(0.0, np.diff(db, prepend=db[0] if db.size else 0.0))
    onset = _robust_scale(delta)
    excitement = np.clip(0.76 * energy + 0.24 * onset, 0.0, 1.0)

    return [
        {
            "time": round(float(t), 3),
            "dbfs": round(float(d), 3),
            "energy": round(float(e), 4),
            "onset": round(float(o), 4),
            "score": round(clamp(float(x)), 4),
        }
        for t, d, e, o, x in zip(times, db, energy, onset, excitement)
    ]
