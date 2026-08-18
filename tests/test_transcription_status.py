from highlightminer.transcription_status import (
    SKIP_REASON_MODEL_DOWNLOADS_DISABLED,
    SKIP_REASON_USER_REQUESTED,
    TRANSCRIPTION_AVAILABLE,
    TRANSCRIPTION_SKIPPED,
    is_transcription_skipped,
    skipped_transcription_metadata,
    transcription_status,
)


def test_skipped_transcription_metadata_uses_canonical_status_and_reason() -> None:
    metadata = skipped_transcription_metadata("large-v3", SKIP_REASON_USER_REQUESTED)

    assert metadata == {
        "status": TRANSCRIPTION_SKIPPED,
        "reason": SKIP_REASON_USER_REQUESTED,
        "model": "large-v3",
    }
    assert is_transcription_skipped(metadata) is True
    assert transcription_status(metadata) == TRANSCRIPTION_SKIPPED


def test_legacy_transcription_without_status_is_treated_as_available() -> None:
    assert is_transcription_skipped({"language": "en"}) is False
    assert transcription_status({"language": "en"}) == TRANSCRIPTION_AVAILABLE


def test_model_download_skip_reason_is_supported() -> None:
    metadata = skipped_transcription_metadata(
        "large-v3",
        SKIP_REASON_MODEL_DOWNLOADS_DISABLED,
    )

    assert metadata["reason"] == SKIP_REASON_MODEL_DOWNLOADS_DISABLED
