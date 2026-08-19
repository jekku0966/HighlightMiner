from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from highlightminer.diagnostics import log_event, log_exception, log_startup
from highlightminer.storage import SCHEMA_VERSION, connect, default_db_path
from highlightminer.ui_common import render_shutdown
from highlightminer.ui_mine import analysis_is_running, render_mine_page
from highlightminer.ui_settings import render_settings_page
from highlightminer.ui_style import apply_shell_style

_NAV_ITEMS = ["⛏️ Mine / Review", "⚙️ Settings"]
_NAV_KEY = "main_navigation"
_DB_DIAGNOSTIC_KEY = "diagnostic_database_initialized"


def _existing_schema_version(db_path: Path) -> str | None:
    if not db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "unknown"
    return str(row[0]) if row else "unknown"


def _initialize_database_with_diagnostics(db_path: Path) -> None:
    if st.session_state.get(_DB_DIAGNOSTIC_KEY):
        return
    before = _existing_schema_version(db_path)
    try:
        with connect(db_path):
            pass
    except Exception as exc:
        log_exception("database.initialization_error", exc)
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
    st.session_state[_DB_DIAGNOSTIC_KEY] = True


def _render_app() -> None:
    st.set_page_config(page_title="HighlightMiner", page_icon="⛏️", layout="wide")
    apply_shell_style()
    db_path = default_db_path()
    _initialize_database_with_diagnostics(db_path)
    running = analysis_is_running()

    with st.container(border=True):
        st.title("⛏️ HighlightMiner")
        st.caption(
            "Mine long VODs for the moments worth keeping — audio + optional local speech recognition + optional chat, "
            "ranked locally on your machine. v0.2 keeps source-aware history, reviews, and app settings in SQLite."
        )

    if running:
        st.session_state[_NAV_KEY] = _NAV_ITEMS[0]

    with st.sidebar:
        st.header("HighlightMiner")
        page = st.radio(
            "Navigate",
            _NAV_ITEMS,
            key=_NAV_KEY,
            label_visibility="collapsed",
            disabled=running,
        )
        if running:
            st.caption("🔒 Analysis in progress. Settings are locked until this run finishes or stops with an error/model decision.")

    if running:
        page = _NAV_ITEMS[0]

    if page == "⚙️ Settings":
        with st.sidebar:
            st.caption(f"Database: `{db_path}`")
            render_shutdown()
        render_settings_page(db_path)
        return

    render_mine_page(db_path)


def main() -> None:
    log_startup(entrypoint="streamlit")
    try:
        _render_app()
    except Exception as exc:
        log_exception("app.unhandled_error", exc)
        raise


if __name__ == "__main__":
    main()
