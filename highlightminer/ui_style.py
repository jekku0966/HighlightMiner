from __future__ import annotations

import streamlit as st

_SIDEBAR_WIDTH = "clamp(26rem, 32vw, 30rem)"


def sidebar_shell_css() -> str:
    """Return the small shell-level CSS Streamlit does not expose as theme options."""
    return f"""
<style>
@media (min-width: 900px) {{
    section[data-testid="stSidebar"] {{
        width: {_SIDEBAR_WIDTH} !important;
        min-width: {_SIDEBAR_WIDTH} !important;
        max-width: {_SIDEBAR_WIDTH} !important;
    }}

    section[data-testid="stSidebar"] > div:first-child {{
        width: 100% !important;
    }}

    section[data-testid="stSidebar"] button p {{
        white-space: nowrap;
    }}
}}
</style>
"""


def apply_shell_style() -> None:
    st.markdown(sidebar_shell_css(), unsafe_allow_html=True)
