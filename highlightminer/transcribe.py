from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .model_access import ModelAccessPreferences, PreparedModelReference, prepare_model_reference
from .runtime import configure_windows_cuda_dll_search
from .transcription_status import TRANSCRIPTION_AVAILABLE
from .util import clamp

# Public faster-whisper/CTranslate2 API usage is based on upstream documentation.
# No faster-whisper source code is vendored here; see ATTRIBUTIONS.md.

_LAUGH_RE = re.compile(r"\b(?:ha(?:ha)+|he(?:he)+|lol|lmao|rofl)\b", re.IGNORECASE)
_PROFANITY = {
    "fuck", "fucking", "shit", "damn", "bitch", "asshole",
    "vittu", "saatana", "perkele", "jumalauta", "helvetti",
}

TranscriptionProgress = Callable[[str, float], None]


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed is not None and math.isfinite(parsed) else None


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _compute_label(compute_type: str) -> str:
    labels = {
        "float16": "FP16",
        "float32": "FP32",
        "int8": "INT8",
        "int8_float16": "INT8/FP16",
        "int8_float32": "INT8/FP32",
        "int16": "INT16",
    }
    return labels.get(compute_type, compute_type.upper())


def _runtime_label(device: str, compute_type: str, model_name: str) -> str:
    if device == "cuda":
        return f"GPU (CUDA · {_compute_label(compute_type)} · {model_name})"
    return f"CPU ({_compute_label(compute_type)} · {model_name})"


def resolve_device(settings: Settings) -> tuple[str, str]:
    if settings.device != "auto":
        compute = settings.compute_type
        if compute == "auto":
            compute = "float16" if settings.device == "cuda" else "int8"
        return settings.device, compute

    try:
        configure_windows_cuda_dll_search()
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16" if settings.compute_type == "auto" else settings.compute_type
    except Exception:
        pass
    return "cpu", "int8" if settings.compute_type == "auto" else settings.compute_type


def score_text(text: str, reaction_phrases: list[str]) -> tuple[float, list[str]]:
    raw = text.strip()
    lower = raw.lower()
    reasons: list[str] = []
    score = 0.0

    hits = [phrase for phrase in reaction_phrases if phrase and phrase.lower() in lower]
    if hits:
        score += min(0.62, 0.28 + 0.13 * len(hits))
        reasons.append("reaction phrase")

    if _LAUGH_RE.search(lower):
        score += 0.46
        reasons.append("laughter")

    words = re.findall(r"[\w']+", raw, flags=re.UNICODE)
    profanity_hits = sum(1 for w in words if w.lower() in _PROFANITY)
    if profanity_hits:
        score += min(0.28, 0.12 * profanity_hits)
        reasons.append("strong reaction")

    exclamations = raw.count("!")
    questions = raw.count("?")
    if exclamations:
        score += min(0.18, exclamations * 0.06)
        reasons.append("exclamation")
    if questions >= 2:
        score += 0.10
        reasons.append("surprise/questioning")

    alpha_words = [w for w in words if any(ch.isalpha() for ch in w)]
    caps = [w for w in alpha_words if len(w) >= 3 and w.isupper()]
    if caps:
        score += min(0.14, 0.05 * len(caps))
        reasons.append("raised/emphatic wording")

    if 1 <= len(words) <= 7 and (hits or exclamations or profanity_hits or caps):
        score += 0.08

    return clamp(score), reasons


def transcribe_audio(
    audio_path: str | Path,
    settings: Settings,
    model_access: ModelAccessPreferences | None = None,
    prepared_model: PreparedModelReference | None = None,
    *,
    audio_duration: float | None = None,
    progress: TranscriptionProgress | None = None,
) -> tuple[list[dict], dict]:
    # On Windows this explicitly exposes the configured portable CUDA/cuDNN DLL directory.
    configure_windows_cuda_dll_search()
    from faster_whisper import WhisperModel

    started_at = time.perf_counter()
    prepared = prepared_model or prepare_model_reference(
        settings,
        model_access or ModelAccessPreferences(),
    )
    device, compute_type = resolve_device(settings)
    fallback_reason = None
    model_kwargs = {
        "local_files_only": prepared.local_files_only,
    }

    def report(message: str, fraction: float) -> None:
        if progress is not None:
            progress(message, clamp(fraction))

    report(
        f"Loading faster-whisper model — {_runtime_label(device, compute_type, prepared.display_name)} · "
        f"elapsed {_format_elapsed(time.perf_counter() - started_at)}",
        0.0,
    )
    try:
        model = WhisperModel(prepared.reference, device=device, compute_type=compute_type, **model_kwargs)
    except Exception as exc:
        if device != "cuda":
            raise
        fallback_reason = f"CUDA initialization failed: {type(exc).__name__}: {exc}"
        device, compute_type = "cpu", "int8"
        report(
            f"CUDA initialization failed; retrying on {_runtime_label(device, compute_type, prepared.display_name)} · "
            f"elapsed {_format_elapsed(time.perf_counter() - started_at)}",
            0.0,
        )
        model = WhisperModel(prepared.reference, device=device, compute_type=compute_type, **model_kwargs)

    kwargs = {
        "beam_size": int(settings.beam_size),
        "vad_filter": bool(settings.vad_filter),
        "word_timestamps": False,
    }
    if settings.language:
        kwargs["language"] = settings.language

    segments, info = model.transcribe(str(audio_path), **kwargs)
    rows: list[dict] = []
    duration = max(0.0, float(audio_duration or 0.0))
    last_report_at = started_at
    last_fraction = -1.0
    furthest_audio_second = 0.0

    def report_transcription(*, force: bool = False) -> None:
        nonlocal last_report_at, last_fraction
        now = time.perf_counter()
        fraction = clamp(furthest_audio_second / duration) if duration > 0 else 0.0
        if not force and (now - last_report_at) < 1.0 and (fraction - last_fraction) < 0.005:
            return
        audio_text = ""
        if duration > 0:
            audio_text = f" · {_format_elapsed(furthest_audio_second)} / {_format_elapsed(duration)} audio"
        report(
            f"Transcribing — {_runtime_label(device, compute_type, prepared.display_name)}"
            f"{audio_text} · elapsed {_format_elapsed(now - started_at)}",
            fraction,
        )
        last_report_at = now
        last_fraction = fraction

    report_transcription(force=True)
    for seg in segments:
        start = _safe_float(getattr(seg, "start", None))
        end = _safe_float(getattr(seg, "end", None))
        if end is not None:
            furthest_audio_second = max(furthest_audio_second, max(0.0, end))
            report_transcription()
        raw_text = getattr(seg, "text", "")
        text = "" if raw_text is None else str(raw_text).strip()
        if start is None or end is None or not text:
            continue

        start = max(0.0, start)
        end = max(start, end)
        score, reasons = score_text(text, settings.reaction_phrases)
        rows.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "score": round(score, 4),
            "reasons": reasons,
        })

    elapsed_seconds = max(0.0, time.perf_counter() - started_at)
    if duration > 0:
        furthest_audio_second = max(furthest_audio_second, duration)
    report_transcription(force=True)

    language_probability = _safe_float(getattr(info, "language_probability", None))
    metadata = {
        "status": TRANSCRIPTION_AVAILABLE,
        "language": getattr(info, "language", None),
        "language_probability": language_probability if language_probability is not None else 0.0,
        "device": device,
        "compute_type": compute_type,
        "model": prepared.display_name,
        "model_source": prepared.source,
        "fallback_reason": fallback_reason,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "audio_duration_seconds": round(duration, 3) if duration > 0 else None,
        "real_time_factor": round(elapsed_seconds / duration, 6) if duration > 0 else None,
    }
    return rows, metadata
