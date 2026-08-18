from __future__ import annotations

import math
import sys
import types

from highlightminer.config import Settings
from highlightminer.model_access import PreparedModelReference
from highlightminer.transcribe import _safe_float, transcribe_audio


def test_safe_float_rejects_non_numeric_and_non_finite_values() -> None:
    assert _safe_float("not-a-number") is None
    assert _safe_float(math.nan) is None
    assert _safe_float(math.inf) is None
    assert _safe_float(None) is None
    assert _safe_float("1.25") == 1.25


def test_transcription_skips_malformed_segments_and_normalizes_valid_metadata(monkeypatch) -> None:
    segments = [
        types.SimpleNamespace(start="bad", end=1.0, text="bad start"),
        types.SimpleNamespace(start=1.0, end=math.inf, text="bad end"),
        types.SimpleNamespace(start=1.0, end=2.0, text=None),
        types.SimpleNamespace(start=-0.2, end=0.4, text=" Valid reaction! "),
        types.SimpleNamespace(start=2.0, end=1.5, text="Clamped end"),
    ]
    info = types.SimpleNamespace(language="en", language_probability=math.nan)

    class FakeModel:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def transcribe(self, _source: str, **_kwargs):
            return iter(segments), info

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    progress_updates: list[tuple[str, float]] = []
    rows, metadata = transcribe_audio(
        "ignored.wav",
        Settings(device="cpu", compute_type="int8"),
        prepared_model=PreparedModelReference(
            reference="large-v3",
            local_files_only=False,
            source="managed",
            display_name="large-v3",
        ),
        audio_duration=4.0,
        progress=lambda message, fraction: progress_updates.append((message, fraction)),
    )

    assert [(row["start"], row["end"], row["text"]) for row in rows] == [
        (0.0, 0.4, "Valid reaction!"),
        (2.0, 2.0, "Clamped end"),
    ]
    assert metadata["language"] == "en"
    assert metadata["language_probability"] == 0.0
    assert metadata["model_source"] == "managed"
    assert metadata["device"] == "cpu"
    assert metadata["compute_type"] == "int8"
    assert metadata["audio_duration_seconds"] == 4.0
    assert metadata["elapsed_seconds"] >= 0.0
    assert metadata["real_time_factor"] is not None
    assert progress_updates
    assert any("CPU (INT8 · large-v3)" in message for message, _ in progress_updates)
    assert any("elapsed 00:00:00" in message for message, _ in progress_updates)
    assert progress_updates[-1][1] >= 0.999
