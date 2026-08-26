import json
import sqlite3
from pathlib import Path

from highlightminer.storage import connect, find_source_runs, load_analysis


def test_pre_source_v02_database_migrates_in_place(tmp_path: Path) -> None:
    video = tmp_path / "old-v02.mp4"
    video.write_bytes(b"old v02 source" * 1000)
    db = tmp_path / "highlightminer.db"

    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE analyses (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            video_path TEXT NOT NULL,
            video_name TEXT NOT NULL,
            content_label TEXT NOT NULL,
            duration REAL NOT NULL,
            work_dir TEXT NOT NULL,
            media_json TEXT NOT NULL,
            transcription_json TEXT NOT NULL,
            chat_json TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            source_version INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        INSERT INTO analyses(
            id, created_at, video_path, video_name, content_label, duration,
            work_dir, media_json, transcription_json, chat_json, settings_json, source_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-v02-run",
            "2026-08-17T12:00:00+00:00",
            str(video.resolve()),
            video.name,
            "Overwatch 2",
            120.0,
            str(tmp_path.resolve()),
            json.dumps({"duration": 120.0}),
            json.dumps({"language": "en"}),
            json.dumps({"path": None, "messages": 0}),
            json.dumps({"max_candidates": 40}),
            2,
        ),
    )
    conn.commit()
    conn.close()

    # Opening through the current storage layer performs the schema migration.
    with connect(db) as migrated:
        columns = {row[1] for row in migrated.execute("PRAGMA table_info(analyses)")}
        assert {"source_id", "source_fingerprint", "run_number", "cache_json"} <= columns
        tables = {
            row[0]
            for row in migrated.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"analysis_jobs", "analysis_job_events"} <= tables
        assert migrated.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0] == "3"

    source, runs = find_source_runs(db, video)
    assert source["fingerprint"]
    assert len(runs) == 1
    assert runs[0]["id"] == "legacy-v02-run"
    assert runs[0]["run_number"] == 1

    loaded = load_analysis(db, "legacy-v02-run")
    assert loaded["source_id"] == source["id"]
    assert loaded["run_number"] == 1
