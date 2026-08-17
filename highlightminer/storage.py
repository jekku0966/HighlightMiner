from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .categorization import normalize_content_label
from .runtime import app_root
from .security import validate_legacy_analysis_file, validate_local_video
from .util import load_json

SCHEMA_VERSION = 1
DATABASE_FILENAME = "highlightminer.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_db_path() -> Path:
    return app_root() / DATABASE_FILENAME


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _unjson(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or default_db_path()).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    initialize(conn)
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS analyses (
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
        );

        CREATE TABLE IF NOT EXISTS candidates (
            analysis_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            score REAL NOT NULL,
            peak_time REAL NOT NULL,
            start REAL NOT NULL,
            end REAL NOT NULL,
            audio_score REAL NOT NULL,
            transcript_score REAL NOT NULL,
            chat_score REAL NOT NULL,
            reason TEXT NOT NULL,
            transcript TEXT NOT NULL,
            content_label TEXT NOT NULL,
            PRIMARY KEY (analysis_id, candidate_id),
            FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reviews (
            analysis_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'unreviewed'
                CHECK (status IN ('unreviewed', 'keep', 'reject')),
            start REAL NOT NULL,
            end REAL NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT,
            updated_at TEXT NOT NULL,
            exported_at TEXT,
            export_path TEXT,
            PRIMARY KEY (analysis_id, candidate_id),
            FOREIGN KEY (analysis_id, candidate_id)
                REFERENCES candidates(analysis_id, candidate_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS transcript_segments (
            analysis_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            start REAL NOT NULL,
            end REAL NOT NULL,
            text TEXT NOT NULL,
            score REAL NOT NULL,
            reasons_json TEXT NOT NULL,
            PRIMARY KEY (analysis_id, seq),
            FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS audio_features (
            analysis_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            time REAL NOT NULL,
            dbfs REAL NOT NULL,
            energy REAL NOT NULL,
            onset REAL NOT NULL,
            score REAL NOT NULL,
            PRIMARY KEY (analysis_id, seq),
            FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS chat_features (
            analysis_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            time REAL NOT NULL,
            count INTEGER NOT NULL,
            ratio REAL NOT NULL,
            score REAL NOT NULL,
            PRIMARY KEY (analysis_id, seq),
            FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_candidates_analysis_rank
            ON candidates(analysis_id, rank);
        CREATE INDEX IF NOT EXISTS idx_reviews_status
            ON reviews(status);
        CREATE INDEX IF NOT EXISTS idx_transcript_analysis_time
            ON transcript_segments(analysis_id, start, end);
        CREATE INDEX IF NOT EXISTS idx_analyses_created
            ON analyses(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_analyses_content
            ON analyses(content_label);
        """
    )
    conn.execute(
        "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def save_analysis(
    db_path: str | Path | None,
    analysis: dict,
    transcript: Iterable[dict],
    audio_features: Iterable[dict],
    chat_features: Iterable[dict],
    *,
    work_dir: str | Path,
    analysis_id: str | None = None,
) -> str:
    analysis_id = analysis_id or uuid.uuid4().hex
    video = validate_local_video(analysis["video_path"])
    content_label = normalize_content_label(analysis.get("content_label"))
    created_at = utc_now()

    candidates = list(analysis.get("candidates", []))
    transcript_rows = list(transcript)
    audio_rows = list(audio_features)
    chat_rows = list(chat_features)

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO analyses(
                id, created_at, video_path, video_name, content_label, duration,
                work_dir, media_json, transcription_json, chat_json, settings_json,
                source_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                created_at,
                str(video),
                video.name,
                content_label,
                float(analysis.get("duration", 0.0)),
                str(Path(work_dir).expanduser().resolve()),
                _json(analysis.get("media", {})),
                _json(analysis.get("transcription", {})),
                _json(analysis.get("chat", {})),
                _json(analysis.get("settings", {})),
                int(analysis.get("version", 1)),
            ),
        )

        for c in candidates:
            cid = str(c["id"])
            conn.execute(
                """
                INSERT INTO candidates(
                    analysis_id, candidate_id, rank, score, peak_time, start, end,
                    audio_score, transcript_score, chat_score, reason, transcript,
                    content_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    cid,
                    int(c.get("rank", 0)),
                    float(c.get("score", 0.0)),
                    float(c.get("peak_time", 0.0)),
                    float(c.get("start", 0.0)),
                    float(c.get("end", 0.0)),
                    float(c.get("audio_score", 0.0)),
                    float(c.get("transcript_score", 0.0)),
                    float(c.get("chat_score", 0.0)),
                    str(c.get("reason", "")),
                    str(c.get("transcript", "")),
                    normalize_content_label(c.get("content_label") or content_label),
                ),
            )
            conn.execute(
                """
                INSERT INTO reviews(
                    analysis_id, candidate_id, status, start, end, title, updated_at
                ) VALUES (?, ?, 'unreviewed', ?, ?, '', ?)
                """,
                (analysis_id, cid, float(c["start"]), float(c["end"]), created_at),
            )

        conn.executemany(
            """
            INSERT INTO transcript_segments(
                analysis_id, seq, start, end, text, score, reasons_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    analysis_id,
                    i,
                    float(row.get("start", 0.0)),
                    float(row.get("end", 0.0)),
                    str(row.get("text", "")),
                    float(row.get("score", 0.0)),
                    _json(row.get("reasons", [])),
                )
                for i, row in enumerate(transcript_rows)
            ],
        )
        conn.executemany(
            """
            INSERT INTO audio_features(
                analysis_id, seq, time, dbfs, energy, onset, score
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    analysis_id,
                    i,
                    float(row.get("time", 0.0)),
                    float(row.get("dbfs", 0.0)),
                    float(row.get("energy", 0.0)),
                    float(row.get("onset", 0.0)),
                    float(row.get("score", 0.0)),
                )
                for i, row in enumerate(audio_rows)
            ],
        )
        conn.executemany(
            """
            INSERT INTO chat_features(
                analysis_id, seq, time, count, ratio, score
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    analysis_id,
                    i,
                    float(row.get("time", 0.0)),
                    int(row.get("count", 0)),
                    float(row.get("ratio", 0.0)),
                    float(row.get("score", 0.0)),
                )
                for i, row in enumerate(chat_rows)
            ],
        )
        conn.commit()
    return analysis_id


def load_analysis(db_path: str | Path | None, analysis_id: str) -> dict:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        if row is None:
            raise KeyError(f"Analysis not found: {analysis_id}")
        candidates = conn.execute(
            "SELECT * FROM candidates WHERE analysis_id = ? ORDER BY rank",
            (analysis_id,),
        ).fetchall()

    result = {
        "version": int(row["source_version"]),
        "analysis_id": row["id"],
        "created_at": row["created_at"],
        "video_path": row["video_path"],
        "video_name": row["video_name"],
        "content_label": row["content_label"],
        "duration": float(row["duration"]),
        "work_dir": row["work_dir"],
        "media": _unjson(row["media_json"], {}),
        "transcription": _unjson(row["transcription_json"], {}),
        "chat": _unjson(row["chat_json"], {}),
        "settings": _unjson(row["settings_json"], {}),
        "candidates": [],
    }
    for c in candidates:
        result["candidates"].append(
            {
                "id": c["candidate_id"],
                "rank": int(c["rank"]),
                "score": float(c["score"]),
                "peak_time": float(c["peak_time"]),
                "start": float(c["start"]),
                "end": float(c["end"]),
                "audio_score": float(c["audio_score"]),
                "transcript_score": float(c["transcript_score"]),
                "chat_score": float(c["chat_score"]),
                "reason": c["reason"],
                "transcript": c["transcript"],
                "content_label": c["content_label"],
            }
        )
    return result


def list_analyses(db_path: str | Path | None, limit: int = 100) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                a.id, a.created_at, a.video_path, a.video_name, a.content_label,
                a.duration,
                COUNT(c.candidate_id) AS candidates,
                SUM(CASE WHEN r.status = 'keep' THEN 1 ELSE 0 END) AS kept,
                SUM(CASE WHEN r.status = 'reject' THEN 1 ELSE 0 END) AS rejected
            FROM analyses a
            LEFT JOIN candidates c ON c.analysis_id = a.id
            LEFT JOIN reviews r
                ON r.analysis_id = c.analysis_id AND r.candidate_id = c.candidate_id
            GROUP BY a.id
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "created_at": r["created_at"],
            "video_path": r["video_path"],
            "video_name": r["video_name"],
            "content_label": r["content_label"],
            "duration": float(r["duration"]),
            "candidates": int(r["candidates"] or 0),
            "kept": int(r["kept"] or 0),
            "rejected": int(r["rejected"] or 0),
        }
        for r in rows
    ]


def load_review(db_path: str | Path | None, analysis_id: str, analysis: dict | None = None) -> dict:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM reviews WHERE analysis_id = ? ORDER BY candidate_id",
            (analysis_id,),
        ).fetchall()
    items = {
        r["candidate_id"]: {
            "status": r["status"],
            "start": float(r["start"]),
            "end": float(r["end"]),
            "title": r["title"],
            "reviewed_at": r["reviewed_at"],
            "exported_at": r["exported_at"],
            "export_path": r["export_path"],
        }
        for r in rows
    }
    if analysis:
        for c in analysis.get("candidates", []):
            items.setdefault(
                c["id"],
                {
                    "status": "unreviewed",
                    "start": c["start"],
                    "end": c["end"],
                    "title": "",
                    "reviewed_at": None,
                    "exported_at": None,
                    "export_path": None,
                },
            )
    return {"version": 2, "items": items}


def save_review(db_path: str | Path | None, analysis_id: str, review: dict) -> None:
    now = utc_now()
    with connect(db_path) as conn:
        for candidate_id, item in review.get("items", {}).items():
            status = str(item.get("status", "unreviewed"))
            if status not in {"unreviewed", "keep", "reject"}:
                raise ValueError(f"Invalid review status: {status}")
            reviewed_at = now if status in {"keep", "reject"} else None
            conn.execute(
                """
                UPDATE reviews
                SET status = ?, start = ?, end = ?, title = ?, reviewed_at = ?, updated_at = ?
                WHERE analysis_id = ? AND candidate_id = ?
                """,
                (
                    status,
                    float(item.get("start", 0.0)),
                    float(item.get("end", 0.0)),
                    str(item.get("title", ""))[:500],
                    reviewed_at,
                    now,
                    analysis_id,
                    candidate_id,
                ),
            )
        conn.commit()


def record_export(
    db_path: str | Path | None,
    analysis_id: str,
    candidate_id: str,
    output_path: str | Path,
) -> None:
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE reviews
            SET exported_at = ?, export_path = ?, updated_at = ?
            WHERE analysis_id = ? AND candidate_id = ?
            """,
            (now, str(Path(output_path).expanduser().resolve()), now, analysis_id, candidate_id),
        )
        conn.commit()


def transcript_window(
    db_path: str | Path | None,
    analysis_id: str,
    start: float,
    end: float,
) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT start, end, text, score, reasons_json
            FROM transcript_segments
            WHERE analysis_id = ? AND end >= ? AND start <= ?
            ORDER BY seq
            """,
            (analysis_id, float(start), float(end)),
        ).fetchall()
    return [
        {
            "start": float(r["start"]),
            "end": float(r["end"]),
            "text": r["text"],
            "score": float(r["score"]),
            "reasons": _unjson(r["reasons_json"], []),
        }
        for r in rows
    ]


def import_legacy_analysis(
    analysis_json: str | Path,
    db_path: str | Path | None = None,
) -> str:
    """Import a v0.1 analysis folder into SQLite.

    The referenced source VOD must still exist locally. Network source paths are
    rejected by validate_local_video before any preview/export can be triggered.
    """
    analysis_path = validate_legacy_analysis_file(analysis_json)
    analysis = load_json(analysis_path)
    validate_local_video(analysis.get("video_path", ""))

    folder = analysis_path.parent
    transcript = load_json(folder / "transcript.json") if (folder / "transcript.json").is_file() else []
    audio_features = load_json(folder / "audio_features.json") if (folder / "audio_features.json").is_file() else []
    chat_features = load_json(folder / "chat_features.json") if (folder / "chat_features.json").is_file() else []

    analysis_id = save_analysis(
        db_path,
        analysis,
        transcript,
        audio_features,
        chat_features,
        work_dir=folder,
    )

    review_path = folder / "review.json"
    if review_path.is_file():
        legacy_review = load_json(review_path)
        save_review(db_path, analysis_id, legacy_review)
    return analysis_id
