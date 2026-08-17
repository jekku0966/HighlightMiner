from __future__ import annotations

import streamlit as st

from highlightminer.storage import default_db_path
from highlightminer.ui_common import render_shutdown
from highlightminer.ui_mine import render_mine_page
from highlightminer.ui_settings import render_settings_page


def main() -> None:
    st.set_page_config(page_title="HighlightMiner", page_icon="⛏️", layout="wide")
    db_path = default_db_path()

    with st.container(border=True):
        st.title("⛏️ HighlightMiner")
        st.caption(
            "Mine long VODs for the moments worth keeping — audio + Whisper + optional chat, "
            "ranked locally on your machine. v0.2 keeps source-aware history, reviews, and app settings in SQLite."
        )

    with st.sidebar:
        st.header("HighlightMiner")
        page = st.radio("Navigate", ["⛏️ Mine / Review", "⚙️ Settings"], label_visibility="collapsed")

    if page == "⚙️ Settings":
        with st.sidebar:
            st.caption(f"Database: `{db_path}`")
            render_shutdown()
        render_settings_page(db_path)
        return

    render_mine_page(db_path)


if __name__ == "__main__":
    main()
