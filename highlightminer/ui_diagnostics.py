from __future__ import annotations

from pathlib import Path

import streamlit as st

from .diagnostic_preferences import (
    detailed_diagnostics_next_run,
    set_detailed_diagnostics_next_run,
)
from .diagnostics import (
    delete_logs,
    diagnostic_summary,
    log_exception,
    open_log_folder,
)
from .local_clipboard import copy_text_to_clipboard

_DETAILED_KEY = "diagnostics_detailed_next_run"


def render_diagnostics_settings(db_path: Path) -> None:
    st.subheader("Diagnostic logging")
    st.caption(
        "Logs stay local on this device and are never uploaded automatically. "
        "Standard logging is intentionally lightweight and always enabled."
    )

    st.checkbox(
        "Standard logging",
        value=True,
        disabled=True,
        help="Always enabled. Keeps the latest five logs, capped at 2 MB each.",
    )

    armed = detailed_diagnostics_next_run(db_path)
    if _DETAILED_KEY not in st.session_state:
        st.session_state[_DETAILED_KEY] = armed
    selected = st.checkbox(
        "Detailed diagnostics for next run",
        key=_DETAILED_KEY,
        help=(
            "Adds redacted settings, media metadata, encoder/model decisions, signal statistics and database operation names "
            "to one Detailed log. It automatically returns to Standard after the run starts processing."
        ),
    )
    if bool(selected) != armed:
        set_detailed_diagnostics_next_run(bool(selected), db_path)
        armed = bool(selected)

    if armed:
        st.info("Detailed diagnostics are armed for the next analysis run only.")
    else:
        st.caption("Detailed diagnostics are off. Standard logging remains active.")

    st.caption("Retention: 5 Standard logs × 2 MB maximum · 2 Detailed logs × 10 MB maximum.")

    open_col, summary_col, delete_col = st.columns(3)
    if open_col.button("Open log folder", width="stretch"):
        try:
            open_log_folder()
            st.success("Opened the local log folder.")
        except Exception as exc:
            log_exception("diagnostics.open_folder_error", exc)
            st.exception(exc)

    if summary_col.button("Copy diagnostic summary", width="stretch"):
        try:
            summary = diagnostic_summary(detailed_armed=armed)
            copy_text_to_clipboard(summary)
            st.success("Diagnostic summary copied to the local clipboard.")
        except Exception as exc:
            log_exception("diagnostics.copy_summary_error", exc)
            st.exception(exc)

    if delete_col.button("Delete logs", width="stretch"):
        try:
            removed = delete_logs()
            st.success(f"Deleted {removed} log file(s). Standard logging restarted with a fresh local log.")
        except Exception as exc:
            log_exception("diagnostics.delete_logs_error", exc)
            st.exception(exc)

    with st.expander("What HighlightMiner never writes to logs"):
        st.write(
            "Transcript text, chat messages, usernames, complete file paths, local model paths, reaction phrases, raw SQL/data, "
            "credentials, environment variables and media contents are excluded from both Standard and Detailed logs."
        )
