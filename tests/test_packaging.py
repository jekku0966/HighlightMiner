from pathlib import Path

import pytest

from highlightminer import __version__
from tools.project_version import read_project_version


ROOT = Path(__file__).resolve().parents[1]


def test_project_version_matches_runtime_version() -> None:
    assert read_project_version(ROOT / "pyproject.toml") == __version__


def test_project_version_rejects_missing_project_version(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'highlightminer-test'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="project.version"):
        read_project_version(pyproject)
