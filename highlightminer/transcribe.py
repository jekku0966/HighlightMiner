from __future__ import annotations

import re
from pathlib import Path

from .config import Settings
from .util import clamp

# Public faster-whisper/CTranslate2 API usage is based on upstream documentation.
# No faster-whisper source code is vendored here; see ATTRIBUTIONS.md.

_LAUGH_RE = re.compile(r"\b(?:ha(?:ha)+|he(?:he)+|lol|lmao|rofl)\b", re.IGNORECASE)
_PROFANITY = {
    "fuck", "fucking", "shit", "damn", "bitch", "asshole",
    "vittu", "saatana", "perkele", "jumalauta", "helvetti",
}


def resolve_device(settings: Settings) -> tuple[str, str]:
    if settings.device != "auto":
        compute = settings.compute_type
        if compute == "auto":
            compute = "float16" if settings.device == "cuda" else "int8"
        return settings.device, compute

    try:
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


def transcribe_audio(audio_path: str | Path, settings: Settings) -> tuple[list[dict], dict]:
    from faster_whisper import WhisperModel

    device, compute_type = resolve_device(settings)
    fallback_reason = None
    try:
        model = WhisperModel(settings.whisper_model, device=device, compute_type=compute_type)
    except Exception as exc:
        if device != "cuda":
            raise
        fallback_reason = f"CUDA initialization failed: {type(exc).__name__}: {exc}"
        device, compute_type = "cpu", "int8"
        model = WhisperModel(settings.whisper_model, device=device, compute_type=compute_type)

    kwargs = {
        "beam_size": int(settings.beam_size),
        "vad_filter": bool(settings.vad_filter),
        "word_timestamps": False,
    }
    if settings.language:
        kwargs["language"] = settings.language

    segments, info = model.transcribe(str(audio_path), **kwargs)
    rows: list[dict] = []
    for seg in segments:
        score, reasons = score_text(seg.text, settings.reaction_phrases)
        rows.append({
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": seg.text.strip(),
            "score": round(score, 4),
            "reasons": reasons,
        })

    metadata = {
        "language": getattr(info, "language", None),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "device": device,
        "compute_type": compute_type,
        "model": settings.whisper_model,
        "fallback_reason": fallback_reason,
    }
    return rows, metadata
