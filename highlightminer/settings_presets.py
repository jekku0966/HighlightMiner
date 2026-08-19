from __future__ import annotations

WEIGHT_PRESETS: dict[str, dict[str, float]] = {
    "Balanced": {"audio": 0.34, "transcript": 0.42, "chat": 0.24},
    "Reaction-heavy": {"audio": 0.20, "transcript": 0.60, "chat": 0.20},
    "Chat-heavy": {"audio": 0.20, "transcript": 0.25, "chat": 0.55},
    "Audio-heavy": {"audio": 0.60, "transcript": 0.25, "chat": 0.15},
}


def normalize_weights(weights: dict[str, float], *, chat_available: bool = True) -> dict[str, float]:
    values = {
        "audio": max(0.0, float(weights.get("audio", 0.0))),
        "transcript": max(0.0, float(weights.get("transcript", 0.0))),
        "chat": max(0.0, float(weights.get("chat", 0.0))) if chat_available else 0.0,
    }
    total = sum(values.values()) or 1.0
    return {key: value / total for key, value in values.items()}


def detect_weight_preset(weights: dict[str, float], *, tolerance: float = 0.005) -> str:
    normalized = normalize_weights(weights)
    for name, preset in WEIGHT_PRESETS.items():
        expected = normalize_weights(preset)
        if all(abs(normalized[key] - expected[key]) <= tolerance for key in expected):
            return name
    return "Custom"


def preset_is_pending(preset: str, weights: dict[str, float]) -> bool:
    """Return whether a selected built-in preset differs from editor weights."""
    return preset in WEIGHT_PRESETS and detect_weight_preset(weights) != preset


def preset_preview(preset: str) -> dict[str, float] | None:
    """Return normalized display weights for a built-in preset."""
    values = WEIGHT_PRESETS.get(preset)
    return normalize_weights(values) if values is not None else None
