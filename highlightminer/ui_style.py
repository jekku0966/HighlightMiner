from __future__ import annotations

import streamlit as st

_SIDEBAR_WIDTH = "clamp(26rem, 32vw, 30rem)"
MODEL_ACCESS_CHOICES_KEY = "model_access_choices"


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


def model_access_choices_css() -> str:
    """Keep the three model-decision buttons aligned without styling other controls."""
    selector = f".st-key-{MODEL_ACCESS_CHOICES_KEY}"
    return f"""
<style>
{selector} div[data-testid="stHorizontalBlock"] {{
    align-items: stretch;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    overflow-x: auto;
}}

{selector} div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
    flex: 1 1 0;
    min-width: 0;
}}

{selector} div[data-testid="stButton"],
{selector} div[data-testid="stButton"] > button {{
    width: 100%;
}}

{selector} div[data-testid="stButton"] > button {{
    height: 3.5rem;
    min-height: 3.5rem;
    justify-content: center;
}}

{selector} div[data-testid="stButton"] > button p {{
    white-space: pre-line;
    overflow-wrap: anywhere;
    line-height: 1.2;
    overflow: visible;
    text-overflow: clip;
    text-align: center;
}}

@media (max-width: 640px) {{
    {selector} div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
        flex: 0 0 12rem !important;
        min-width: 12rem;
    }}
}}
</style>
"""


def apply_shell_style() -> None:
    st.markdown(sidebar_shell_css(), unsafe_allow_html=True)
