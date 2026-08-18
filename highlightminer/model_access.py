from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Settings
from .runtime import app_root
from .security import is_network_path
from .storage import connect, utc_now

_DOWNLOAD_CONSENTS = {"unset", "allow", "deny"}
_REQUIRED_LOCAL_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")


class ModelDecisionRequired(RuntimeError):
    """A missing recognition model needs an explicit interactive decision."""


@dataclass(frozen=True)
class ModelAccessPreferences:
    download_consent: str = "unset"
    local_model_path: str | None = None


@dataclass(frozen=True)
class PreparedModelReference:
    reference: str
    local_files_only: bool
    source: str
    display_name: str


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_access_preferences (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            download_consent TEXT NOT NULL DEFAULT 'unset'
                CHECK (download_consent IN ('unset', 'allow', 'deny')),
            local_model_path TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def models_root() -> Path:
    path = app_root() / "models"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def huggingface_cache_directory() -> Path:
    explicit_hub = os.environ.get("HF_HUB_CACHE", "").strip()
    if explicit_hub:
        return Path(explicit_hub).expanduser()
    explicit_home = os.environ.get("HF_HOME", "").strip()
    if explicit_home:
        return Path(explicit_home).expanduser() / "hub"
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        return Path(xdg_cache).expanduser() / "huggingface" / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _normalize_local_model_path(path: str | Path | None) -> str | None:
    raw = "" if path is None else str(path).strip()
    if not raw:
        return None
    if is_network_path(raw):
        raise ValueError("Network paths are not allowed for local Whisper models.")
    resolved = Path(raw).expanduser().resolve(strict=False)
    if is_network_path(resolved):
        raise ValueError("Network paths are not allowed for local Whisper models.")
    return str(resolved)


def load_model_access(db_path: str | Path | None = None) -> ModelAccessPreferences:
    with connect(db_path) as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT download_consent, local_model_path FROM model_access_preferences WHERE id = 1"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO model_access_preferences(id, download_consent, local_model_path, updated_at) VALUES(1, 'unset', NULL, ?)",
                (utc_now(),),
            )
            conn.commit()
            return ModelAccessPreferences()
        return ModelAccessPreferences(
            download_consent=str(row["download_consent"]),
            local_model_path=row["local_model_path"],
        )


def save_model_access(
    preferences: ModelAccessPreferences,
    db_path: str | Path | None = None,
) -> ModelAccessPreferences:
    consent = str(preferences.download_consent).strip().lower()
    if consent not in _DOWNLOAD_CONSENTS:
        raise ValueError(f"download_consent must be one of {sorted(_DOWNLOAD_CONSENTS)}")
    local_model_path = _normalize_local_model_path(preferences.local_model_path)
    if local_model_path:
        validate_local_model_directory(local_model_path)

    saved = ModelAccessPreferences(consent, local_model_path)
    with connect(db_path) as conn:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO model_access_preferences(id, download_consent, local_model_path, updated_at)
            VALUES(1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                download_consent = excluded.download_consent,
                local_model_path = excluded.local_model_path,
                updated_at = excluded.updated_at
            """,
            (saved.download_consent, saved.local_model_path, utc_now()),
        )
        conn.commit()
    return saved


def set_model_download_consent(
    consent: str,
    db_path: str | Path | None = None,
) -> ModelAccessPreferences:
    current = load_model_access(db_path)
    return save_model_access(ModelAccessPreferences(consent, current.local_model_path), db_path)


def validate_local_model_directory(path: str | Path) -> Path:
    normalized = _normalize_local_model_path(path)
    if not normalized:
        raise ValueError("Choose a local Whisper model folder.")
    resolved = Path(normalized).resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"Expected a local Whisper model folder: {resolved}")
    missing = [name for name in _REQUIRED_LOCAL_MODEL_FILES if not (resolved / name).is_file()]
    if missing:
        raise ValueError("Local Whisper model folder is incomplete. Missing: " + ", ".join(missing))
    return resolved


def model_signature_payload(settings: Settings, preferences: ModelAccessPreferences) -> str | dict:
    if not preferences.local_model_path:
        return settings.whisper_model

    normalized = _normalize_local_model_path(preferences.local_model_path)
    assert normalized is not None
    root = Path(normalized)
    files: dict[str, dict[str, int] | None] = {}
    for name in _REQUIRED_LOCAL_MODEL_FILES:
        path = root / name
        try:
            stat = path.stat()
            files[name] = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
        except OSError:
            files[name] = None
    return {"source": "local", "path": normalized, "files": files}


def resolve_model_reference(
    settings: Settings,
    preferences: ModelAccessPreferences,
    *,
    allow_download_override: bool = False,
    download_model_fn: Callable[..., str] | None = None,
) -> PreparedModelReference | None:
    """Resolve local/cache/download access without surprising networking."""
    if preferences.local_model_path:
        local = validate_local_model_directory(preferences.local_model_path)
        return PreparedModelReference(str(local), True, "local", local.name)

    if download_model_fn is None:
        from faster_whisper.utils import download_model
        download_model_fn = download_model

    try:
        cached_path = download_model_fn(settings.whisper_model, local_files_only=True)
    except Exception:
        cached_path = None
    if cached_path:
        return PreparedModelReference(str(cached_path), True, "cache", settings.whisper_model)

    if allow_download_override or preferences.download_consent == "allow":
        return PreparedModelReference(settings.whisper_model, False, "managed", settings.whisper_model)
    if preferences.download_consent == "deny":
        return None

    raise ModelDecisionRequired(
        f"The speech-recognition model {settings.whisper_model!r} is not installed. "
        "Choose whether to download it, select a local CTranslate2 Whisper model folder, "
        "or continue this analysis without speech recognition."
    )


def prepare_model_reference(
    settings: Settings,
    preferences: ModelAccessPreferences,
    *,
    download_model_fn: Callable[..., str] | None = None,
) -> PreparedModelReference:
    try:
        prepared = resolve_model_reference(settings, preferences, download_model_fn=download_model_fn)
    except ModelDecisionRequired as exc:
        raise RuntimeError(
            f"{exc} Open Settings → Analysis engine to explicitly allow model downloads or choose a local model."
        ) from exc
    if prepared is None:
        raise RuntimeError(
            f"The speech-recognition model {settings.whisper_model!r} is not available locally and model downloading is disabled. "
            "Open Settings → Analysis engine to allow downloads or choose a local CTranslate2 Whisper model folder."
        )
    return prepared
