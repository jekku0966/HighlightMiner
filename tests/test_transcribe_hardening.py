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

    rows, metadata = transcribe_audio(
        "ignored.wav",
        Settings(device="cpu", compute_type="int8"),
        prepared_model=PreparedModelReference(
            reference="large-v3",
            local_files_only=False,
            source="managed",
            display_name="large-v3",
        ),
    )

    assert [(row["start"], row["end"], row["text"]) for row in rows] == [
        (0.0, 0.4, "Valid reaction!"),
        (2.0, 2.0, "Clamped end"),
    ]
    assert metadata["language"] == "en"
    assert metadata["language_probability"] == 0.0
    assert metadata["model_source"] == "managed"
