from __future__ import annotations

from typing import Any

TRANSCRIPTION_AVAILABLE = "available"
TRANSCRIPTION_SKIPPED = "skipped"
SKIP_REASON_USER_REQUESTED = "user_requested_no_transcription"
SKIP_REASON_MODEL_DOWNLOADS_DISABLED = "model_downloads_disabled"

_VALID_SKIP_REASONS = {
    SKIP_REASON_USER_REQUESTED,
    SKIP_REASON_MODEL_DOWNLOADS_DISABLED,
}


def skipped_transcription_metadata(model_name: str, reason: str) -> dict[str, Any]:
    """Build the canonical metadata for a deliberately skipped Whisper stage."""
    if reason not in _VALID_SKIP_REASONS:
        raise ValueError(f"Unsupported transcription skip reason: {reason!r}")
    return {
        "status": TRANSCRIPTION_SKIPPED,
        "reason": reason,
        "model": str(model_name),
    }


def is_transcription_skipped(metadata: dict[str, Any] | None) -> bool:
    return str((metadata or {}).get("status") or "") == TRANSCRIPTION_SKIPPED


def transcription_status(metadata: dict[str, Any] | None) -> str:
    """Return a stable persisted status, treating legacy transcripts as available."""
    return TRANSCRIPTION_SKIPPED if is_transcription_skipped(metadata) else TRANSCRIPTION_AVAILABLE
