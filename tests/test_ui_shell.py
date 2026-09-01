from __future__ import annotations

import ast
from pathlib import Path

from streamlit import config as streamlit_config

from highlightminer.cli import _STREAMLIT_FLAG_OPTIONS


ROOT = Path(__file__).resolve().parents[1]
HEADING_METHODS = {"title", "header", "subheader"}


def test_streamlit_toolbar_is_minimal_in_source_and_frozen_launches() -> None:
    assert streamlit_config.get_option("client.toolbarMode") == "minimal"
    assert _STREAMLIT_FLAG_OPTIONS["client_toolbarMode"] == "minimal"


def test_every_streamlit_heading_hides_its_permalink_anchor() -> None:
    missing: list[str] = []
    for path in sorted((ROOT / "highlightminer").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in HEADING_METHODS:
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "st":
                continue
            anchor = next((keyword.value for keyword in node.keywords if keyword.arg == "anchor"), None)
            if not isinstance(anchor, ast.Constant) or anchor.value is not False:
                missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert missing == [], f"Streamlit headings missing anchor=False: {', '.join(missing)}"
