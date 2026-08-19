from __future__ import annotations

import logging
import os
from pathlib import Path

from highlightminer import diagnostics
from highlightminer.config import Settings
from highlightminer.diagnostic_preferences import (
    consume_detailed_diagnostics_next_run,
    detailed_diagnostics_next_run,
    set_detailed_diagnostics_next_run,
)


def test_logging_policy_constants_match_product_limits() -> None:
    assert diagnostics.STANDARD_MAX_BYTES == 2 * 1024 * 1024
    assert diagnostics.DETAILED_MAX_BYTES == 10 * 1024 * 1024
    assert diagnostics.STANDARD_RETAIN == 5
    assert diagnostics.DETAILED_RETAIN == 2


def test_redaction_blocks_sensitive_fields_and_paths() -> None:
    payload = diagnostics._safe_value(
        {
            "video_path": r"C:\Users\alice\Videos\stream.mp4",
            "local_model_path": r"D:\models\private-whisper",
            "transcript_text": "secret spoken words",
            "chat_message": "secret chat",
            "username": "alice",
            "reaction_phrases": ["oh my god"],
            "sql": "SELECT * FROM candidates",
            "credential": "token=abc123",
            "safe": r"failure beside C:\Users\alice\Videos\stream.mp4",
        }
    )
    encoded = str(payload)
    assert "secret spoken words" not in encoded
    assert "secret chat" not in encoded
    assert "alice" not in encoded
    assert "oh my god" not in encoded
    assert "SELECT *" not in encoded
    assert "abc123" not in encoded
    assert r"C:\Users" not in encoded
    assert "<redacted>" in encoded
    assert "<path>" in encoded


def test_safe_traceback_keeps_stack_but_drops_exception_message_and_directories() -> None:
    try:
        raise RuntimeError(r"PRIVATE CHAT C:\Users\alice\Videos\stream.mp4")
    except RuntimeError as exc:
        rendered = diagnostics._safe_traceback(exc)

    assert "Traceback (most recent call last):" in rendered
    assert "test_safe_traceback_keeps_stack" in rendered
    assert "test_diagnostics.py" in rendered
    assert "RuntimeError: <message redacted>" in rendered
    assert "PRIVATE CHAT" not in rendered
    assert "alice" not in rendered
    assert r"C:\Users" not in rendered


def test_redacted_settings_never_include_reaction_phrase_values() -> None:
    settings = Settings(reaction_phrases=["PRIVATE REACTION PHRASE"])
    data = diagnostics.redacted_settings(settings)
    encoded = str(diagnostics._safe_value(data))
    assert "PRIVATE REACTION PHRASE" not in encoded
    assert "reaction_phrases" in data
    assert data["reaction_phrases"] == "<redacted>"


def test_bounded_handler_never_exceeds_limit(tmp_path: Path) -> None:
    target = tmp_path / "bounded.log"
    handler = diagnostics._BoundedFileHandler(target, max_bytes=256)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("highlightminer.test.bounded")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        for _ in range(50):
            logger.info("x" * 64)
    finally:
        handler.close()
        logger.handlers[:] = []
    assert target.stat().st_size <= 256


def _make_logs(tmp_path: Path, prefix: str, count: int) -> None:
    for index in range(count):
        path = tmp_path / f"{prefix}{index}.log"
        path.write_text(str(index), encoding="utf-8")
        os.utime(path, (1000 + index, 1000 + index))


def test_retention_keeps_latest_five_standard_logs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics, "log_folder", lambda: tmp_path)
    _make_logs(tmp_path, "standard-", 7)
    diagnostics._prune("standard-", diagnostics.STANDARD_RETAIN)
    remaining = {path.name for path in tmp_path.glob("standard-*.log")}
    assert remaining == {f"standard-{index}.log" for index in range(2, 7)}


def test_retention_keeps_latest_two_detailed_logs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics, "log_folder", lambda: tmp_path)
    _make_logs(tmp_path, "detailed-", 5)
    diagnostics._prune("detailed-", diagnostics.DETAILED_RETAIN)
    remaining = {path.name for path in tmp_path.glob("detailed-*.log")}
    assert remaining == {"detailed-3.log", "detailed-4.log"}


def test_detailed_next_run_is_consumed_once(tmp_path: Path) -> None:
    db_path = tmp_path / "diagnostics.db"
    assert not detailed_diagnostics_next_run(db_path)
    assert set_detailed_diagnostics_next_run(True, db_path)
    assert detailed_diagnostics_next_run(db_path)
    assert consume_detailed_diagnostics_next_run(db_path)
    assert not detailed_diagnostics_next_run(db_path)
    assert not consume_detailed_diagnostics_next_run(db_path)
