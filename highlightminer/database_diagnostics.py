from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .diagnostics import log_event, log_exception, log_detailed
from .storage import SCHEMA_VERSION, connect, default_db_path

_LOGGED_DATABASES: set[str] = set()
_LOCK = threading.RLock()


def _previous_schema_version(path: Path, existed: bool) -> str | None:
    if not existed:
        return None
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        try:
            row = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "unknown"
    return str(row[0]) if row else "unknown"


def initialize_database_with_diagnostics(db_path: str | Path | None = None) -> None:
    """Initialize/migrate one database and log the result once per process."""
    path = Path(db_path or default_db_path()).expanduser().resolve()
    key = str(path)
    with _LOCK:
        if key in _LOGGED_DATABASES:
            return

        existed = path.is_file()
        before = _previous_schema_version(path, existed)
        log_detailed("database.operation", operation="initialize_database")
        try:
            conn = connect(path)
            conn.close()
        except Exception as exc:
            log_exception(
                "database.initialization_error",
                exc,
                previous_schema_version=before,
                target_schema_version=SCHEMA_VERSION,
            )
            raise

        after = str(SCHEMA_VERSION)
        if before is None:
            result = "created"
        elif before == after:
            result = "up_to_date"
        else:
            result = f"migrated_{before}_to_{after}"
        log_event(
            "database.schema",
            schema_version=SCHEMA_VERSION,
            previous_schema_version=before,
            migration_result=result,
        )
        _LOGGED_DATABASES.add(key)
