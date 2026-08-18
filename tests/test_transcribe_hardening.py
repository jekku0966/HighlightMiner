from __future__ import annotations

import math
import sys
import types

from highlightminer import transcribe
from highlightminer.config import Settings
from highlightminer.model_access import PreparedModelReference
from highlightminer.transcribe import _safe_float, transcribe_audio


def test_safe_float_rejects_non_numeric_and_non_finite_values() -> None:
    assert _safe_float("not-a-number") is None
    assert _safe_float(math.nan) is None
    assert _safe_float(math.inf) is None
    assert _safe_float(None) is None
    assert _safe_float("1.25") == 1.25


def test_cpu_thread_count_reserves_one_physical_core(monkeypatch) -> None:
    def fake_cpu_count(logical: bool = True) -> int:
        return 32 if logical else 16

    monkeypatch.setattr(transcribe.psutil, "cpu_count", fake_cpu_count)
    assert transcribe._cpu_thread_count() == 15


def test_cpu_thread_count_keeps_one_core_system_usable(monkeypatch) -> None:
    monkeypatch.setattr(transcribe.psutil, "cpu_count", lambda logical=True: 1)
    assert transcribe._cpu_thread_count() == 1


def test_cpu_thread_count_is_conservative_when_physical_count_is_unknown(monkeypatch) -> None:
    def fake_cpu_count(logical: bool = True):
        return 32 if logical else None

    monkeypatch.setattr(transcribe.psutil, "cpu_count", fake_cpu_count)
    assert transcribe._cpu_thread_count() == 4


def test_transcription_skips_malformed_segments_and_normalizes_valid_metadata(monkeypatch) -> None:
    segments = [
        types.SimpleNamespace(start="bad", end=1.0, text="bad start"),
        types.SimpleNamespace(start=1.0, end=math.inf, text="bad end"),
        types.SimpleNamespace(start=1.0, end=2.0, text=None),
        types.SimpleNamespace(start=-0.2, end=0.4, text=" Valid reaction! "),
        types.SimpleNamespace(start=2.0, end=1.5, text="Clamped end"),
    ]
    info = types.SimpleNamespace(language="en", language_probability=math.nan)
    model_inits: list[dict] = []

    class FakeModel:
        def __init__(self, *_args, **kwargs) -> None:
            model_inits.append(kwargs)

        def transcribe(self, _source: str, **_kwargs):
            return iter(segments), info

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(transcribe, "_cpu_thread_count", lambda: 7)

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
    assert model_inits[0]["cpu_threads"] == 7
    assert metadata["language"] == "en"
    assert metadata["language_probability"] == 0.0
    assert metadata["model_source"] == "managed"
    assert metadata["device"] == "cpu"
    assert metadata["compute_type"] == "int8"
    assert metadata["cpu_threads"] == 7
    assert metadata["audio_duration_seconds"] == 4.0
    assert metadata["elapsed_seconds"] >= 0.0
    assert metadata["real_time_factor"] is not None
    assert progress_updates
    assert any("CPU (INT8 · large-v3 · 7 threads)" in message for message, _ in progress_updates)
    assert any("elapsed 00:00:00" in message for message, _ in progress_updates)
    assert progress_updates[-1][1] >= 0.999


def test_cuda_initialization_fallback_applies_cpu_thread_budget(monkeypatch) -> None:
    info = types.SimpleNamespace(language="en", language_probability=1.0)
    model_inits: list[dict] = []

    class FakeModel:
        def __init__(self, *_args, **kwargs) -> None:
            model_inits.append(kwargs)
            if kwargs["device"] == "cuda":
                raise RuntimeError("simulated CUDA initialization failure")

        def transcribe(self, _source: str, **_kwargs):
            return iter([]), info

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(transcribe, "resolve_device", lambda _settings: ("cuda", "float16"))
    monkeypatch.setattr(transcribe, "_cpu_thread_count", lambda: 7)

    _rows, metadata = transcribe_audio(
        "ignored.wav",
        Settings(),
        prepared_model=PreparedModelReference(
            reference="large-v3",
            local_files_only=True,
            source="cache",
            display_name="large-v3",
        ),
    )

    assert len(model_inits) == 2
    assert model_inits[0]["device"] == "cuda"
    assert "cpu_threads" not in model_inits[0]
    assert model_inits[1]["device"] == "cpu"
    assert model_inits[1]["compute_type"] == "int8"
    assert model_inits[1]["cpu_threads"] == 7
    assert metadata["device"] == "cpu"
    assert metadata["compute_type"] == "int8"
    assert metadata["cpu_threads"] == 7
    assert metadata["fallback_reason"].startswith("CUDA initialization failed: RuntimeError")
