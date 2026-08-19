from __future__ import annotations

from pathlib import Path

from .diagnostics import log_detailed
from .storage import connect

_DETAILED_NEXT_RUN_KEY = "detailed_diagnostics_next_run"


def detailed_diagnostics_next_run(db_path: str | Path | None = None) -> bool:
    with connect(db_path) as conn:
        log_detailed("database.operation", operation="load_diagnostic_preference")
        row = conn.execute("SELECT value FROM metadata WHERE key = ?", (_DETAILED_NEXT_RUN_KEY,)).fetchone()
    return bool(row is not None and str(row["value"]) == "1")


def set_detailed_diagnostics_next_run(enabled: bool, db_path: str | Path | None = None) -> bool:
    value = "1" if enabled else "0"
    with connect(db_path) as conn:
        log_detailed("database.operation", operation="save_diagnostic_preference")
        conn.execute(
            """
            INSERT INTO metadata(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (_DETAILED_NEXT_RUN_KEY, value),
        )
        conn.commit()
    return bool(enabled)


def consume_detailed_diagnostics_next_run(db_path: str | Path | None = None) -> bool:
    """Atomically consume the one-shot flag before an analysis starts."""
    with connect(db_path) as conn:
        log_detailed("database.operation", operation="consume_diagnostic_preference")
        row = conn.execute("SELECT value FROM metadata WHERE key = ?", (_DETAILED_NEXT_RUN_KEY,)).fetchone()
        enabled = bool(row is not None and str(row["value"]) == "1")
        if enabled:
            conn.execute(
                """
                INSERT INTO metadata(key, value) VALUES(?, '0')
                ON CONFLICT(key) DO UPDATE SET value = '0'
                """,
                (_DETAILED_NEXT_RUN_KEY,),
            )
            conn.commit()
    return enabled
