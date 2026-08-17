from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings
from .runtime import app_root
from .security import is_network_path
from .settings_presets import detect_weight_preset
from .storage import connect, utc_now


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            settings_json TEXT NOT NULL,
            preset_name TEXT NOT NULL DEFAULT 'Custom',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _from_payload(data: dict[str, Any]) -> Settings:
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object.")
    valid = {key: value for key, value in data.items() if key in Settings.__dataclass_fields__}
    return Settings(**valid)


def _product_defaults() -> Settings:
    packaged = app_root() / "settings.json"
    if packaged.is_file():
        try:
            return Settings.from_file(packaged)
        except Exception:
            pass
    return Settings()


def load_app_settings(db_path: str | Path | None = None) -> Settings:
    with connect(db_path) as conn:
        _ensure_table(conn)
        row = conn.execute("SELECT settings_json FROM app_settings WHERE id = 1").fetchone()
        if row is not None:
            return _from_payload(json.loads(row["settings_json"]))

        settings = _product_defaults()
        payload = settings.__dict__.copy()
        conn.execute(
            "INSERT INTO app_settings(id, settings_json, preset_name, updated_at) VALUES(1, ?, ?, ?)",
            (json.dumps(payload, ensure_ascii=False), detect_weight_preset(settings.weights), utc_now()),
        )
        conn.commit()
        return settings


def save_app_settings(settings: Settings, db_path: str | Path | None = None) -> Settings:
    settings.validate()
    payload = settings.__dict__.copy()
    preset = detect_weight_preset(settings.weights)
    with connect(db_path) as conn:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO app_settings(id, settings_json, preset_name, updated_at)
            VALUES(1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                settings_json = excluded.settings_json,
                preset_name = excluded.preset_name,
                updated_at = excluded.updated_at
            """,
            (json.dumps(payload, ensure_ascii=False), preset, utc_now()),
        )
        conn.commit()
    return settings


def reset_app_settings(db_path: str | Path | None = None) -> Settings:
    return save_app_settings(_product_defaults(), db_path)


def import_app_settings(path: str | Path, db_path: str | Path | None = None) -> Settings:
    return save_app_settings(Settings.from_file(path), db_path)


def export_app_settings(path: str | Path, db_path: str | Path | None = None) -> Path:
    raw = str(path).strip()
    if not raw:
        raise ValueError("Choose a destination for the settings export.")
    if is_network_path(raw):
        raise ValueError("Network paths are not allowed for settings export.")
    destination = Path(raw).expanduser()
    if destination.suffix.lower() != ".json":
        destination = destination.with_suffix(".json")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    settings = load_app_settings(db_path)
    destination.write_text(
        json.dumps(settings.__dict__, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
