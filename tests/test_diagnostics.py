from __future__ import annotations

import logging
import os
from pathlib import Path

from highlightminer.config import Settings
from highlightminer.diagnostic_preferences import (
    consume_detailed_diagnostics_next_run,
    detailed_diagnostics_next_run,
    set_detailed_diagnostics_next_run,
)
from highlightminer import diagnostics


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


def test_retention_keeps_latest_standard_logs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics, "log_folder", lambda: tmp_path)
    files = []
    for index in range(7):
        path = tmp_path / f"standard-{index}.log"
        path.write_text(str(index), encoding="utf-8")
        os.utime(path, (1000 + index, 1000 + index))
        files.append(path)

    diagnostics._prune("standard-", 5)
    remaining = {path.name for path in tmp_path.glob("standard-*.log")}
    assert remaining == {f"standard-{index}.log" for index in range(2, 7)}


def test_detailed_next_run_is_consumed_once(tmp_path: Path) -> None:
    db_path = tmp_path / "diagnostics.db"
    assert not detailed_diagnostics_next_run(db_path)
    assert set_detailed_diagnostics_next_run(True, db_path)
    assert detailed_diagnostics_next_run(db_path)
    assert consume_detailed_diagnostics_next_run(db_path)
    assert not detailed_diagnostics_next_run(db_path)
    assert not consume_detailed_diagnostics_next_run(db_path)
