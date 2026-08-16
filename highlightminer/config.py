from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import load_json


@dataclass
class Settings:
    whisper_model: str = "large-v3"
    device: str = "auto"
    compute_type: str = "auto"
    language: str | None = None
    beam_size: int = 5
    vad_filter: bool = True
    audio_window_sec: float = 1.0
    audio_hop_sec: float = 0.5
    pre_roll_sec: float = 18.0
    post_roll_sec: float = 14.0
    merge_gap_sec: float = 10.0
    max_candidate_sec: float = 75.0
    min_candidate_score: float = 0.38
    max_candidates: int = 40
    weights: dict[str, float] = field(default_factory=lambda: {
        "audio": 0.34, "transcript": 0.42, "chat": 0.24
    })
    reaction_phrases: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str | Path | None) -> "Settings":
        if path is None:
            return cls()
        data = load_json(path)
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    def normalized_weights(self, chat_available: bool) -> dict[str, float]:
        weights = dict(self.weights)
        if not chat_available:
            weights["chat"] = 0.0
        total = sum(max(0.0, float(v)) for v in weights.values()) or 1.0
        return {k: max(0.0, float(v)) / total for k, v in weights.items()}
