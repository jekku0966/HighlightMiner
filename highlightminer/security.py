from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

# Deliberately generous limits: these are guard rails against absurd/untrusted
# inputs, not arbitrary restrictions on normal VOD workflows.
MAX_SETTINGS_BYTES = 2 * 1024 * 1024
MAX_LEGACY_ANALYSIS_BYTES = 64 * 1024 * 1024
MAX_CHAT_BYTES = 1024 * 1024 * 1024
MAX_JSON_LINE_BYTES = 16 * 1024 * 1024
MAX_JSON_NESTING = 64


def is_network_path(path: str | Path) -> bool:
    """Return True for UNC/network-style paths.

    HighlightMiner is a local desktop-style application. Automatic access to
    network paths stored in imported data is intentionally rejected so a
    crafted analysis/database cannot silently trigger SMB/network access.
    """
    raw = os.fspath(path).strip()
    if raw.startswith("\\\\") or raw.startswith("//"):
        return True
    if os.name == "nt":
        try:
            from pathlib import PureWindowsPath

            return bool(PureWindowsPath(raw).drive.startswith("\\\\"))
        except Exception:
            return False
    return False


def validate_local_file(
    path: str | Path,
    *,
    allowed_suffixes: Iterable[str] | None = None,
    max_bytes: int | None = None,
    reject_network: bool = True,
    description: str = "file",
) -> Path:
    """Resolve and validate a user- or database-supplied local file path."""
    if not str(path).strip():
        raise ValueError(f"No {description} was selected.")
    if reject_network and is_network_path(path):
        raise ValueError(f"Network paths are not allowed for {description}: {path}")

    p = Path(path).expanduser().resolve(strict=True)
    if not p.is_file():
        raise ValueError(f"Expected a regular {description}: {p}")

    if allowed_suffixes:
        allowed = {str(x).lower() for x in allowed_suffixes}
        if p.suffix.lower() not in allowed:
            raise ValueError(
                f"Unsupported {description} type {p.suffix!r}. Allowed: {', '.join(sorted(allowed))}"
            )

    if max_bytes is not None:
        size = p.stat().st_size
        if size > int(max_bytes):
            raise ValueError(
                f"{description.capitalize()} is too large ({size:,} bytes; limit {int(max_bytes):,})."
            )
    return p


def validate_local_video(path: str | Path) -> Path:
    return validate_local_file(
        path,
        allowed_suffixes={".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts"},
        description="VOD",
    )


def validate_chat_file(path: str | Path) -> Path:
    return validate_local_file(
        path,
        allowed_suffixes={".json", ".jsonl", ".ndjson", ".csv"},
        max_bytes=MAX_CHAT_BYTES,
        description="chat file",
    )


def validate_settings_file(path: str | Path) -> Path:
    return validate_local_file(
        path,
        allowed_suffixes={".json"},
        max_bytes=MAX_SETTINGS_BYTES,
        description="settings file",
    )


def validate_legacy_analysis_file(path: str | Path) -> Path:
    return validate_local_file(
        path,
        allowed_suffixes={".json"},
        max_bytes=MAX_LEGACY_ANALYSIS_BYTES,
        description="legacy analysis file",
    )
