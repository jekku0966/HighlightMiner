from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .settings_presets import detect_weight_preset
from .storage import connect

_ANALYSIS_TITLE_PREFIX = "analysis_title:"
_MAX_ANALYSIS_TITLE_LENGTH = 200


def analysis_name_from_settings(settings: Mapping[str, Any] | None) -> str:
    """Derive the run's analysis name from its immutable weight snapshot."""
    if not settings:
        return "Custom"
    weights = settings.get("weights")
    if not isinstance(weights, Mapping):
        return "Custom"
    try:
        return detect_weight_preset(dict(weights))
    except (TypeError, ValueError):
        return "Custom"


def normalize_analysis_title(title: str | None) -> str:
    return str(title or "").strip()[:_MAX_ANALYSIS_TITLE_LENGTH]


def _title_key(analysis_id: str) -> str:
    return f"{_ANALYSIS_TITLE_PREFIX}{analysis_id}"


def save_analysis_title(db_path: str | Path | None, analysis_id: str, title: str | None) -> str:
    """Persist optional user-entered run title separately from analysis settings."""
    cleaned = normalize_analysis_title(title)
    with connect(db_path) as conn:
        exists = conn.execute("SELECT 1 FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        if exists is None:
            raise KeyError(f"Analysis not found: {analysis_id}")
        key = _title_key(analysis_id)
        if cleaned:
            conn.execute(
                """
                INSERT INTO metadata(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, cleaned),
            )
        else:
            conn.execute("DELETE FROM metadata WHERE key = ?", (key,))
        conn.commit()
    return cleaned


def load_analysis_identities(
    db_path: str | Path | None,
    analysis_ids: Sequence[str],
) -> dict[str, dict[str, str]]:
    """Load derived weight-profile names and optional titles for analysis runs."""
    ids = list(dict.fromkeys(str(value) for value in analysis_ids if value))
    if not ids:
        return {}

    placeholders = ",".join("?" for _ in ids)
    title_keys = [_title_key(analysis_id) for analysis_id in ids]
    title_placeholders = ",".join("?" for _ in title_keys)

    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT id, settings_json FROM analyses WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        title_rows = conn.execute(
            f"SELECT key, value FROM metadata WHERE key IN ({title_placeholders})",
            title_keys,
        ).fetchall()

    titles = {
        str(row["key"])[len(_ANALYSIS_TITLE_PREFIX):]: normalize_analysis_title(row["value"])
        for row in title_rows
    }
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        analysis_id = str(row["id"])
        try:
            settings = json.loads(row["settings_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            settings = {}
        result[analysis_id] = {
            "analysis_name": analysis_name_from_settings(settings if isinstance(settings, Mapping) else {}),
            "analysis_title": titles.get(analysis_id, ""),
        }
    return result


def load_analysis_identity(db_path: str | Path | None, analysis_id: str) -> dict[str, str]:
    identity = load_analysis_identities(db_path, [analysis_id]).get(analysis_id)
    if identity is None:
        raise KeyError(f"Analysis not found: {analysis_id}")
    return identity
