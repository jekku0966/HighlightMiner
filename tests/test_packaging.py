import json
from pathlib import Path

import pytest

from highlightminer import __version__
from tools.project_version import read_project_version


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_RELEASE_DOCUMENTS = {
    "README.md",
    "BUILD_WINDOWS.md",
    "ATTRIBUTIONS.md",
    "SECURITY.md",
    "LICENSE",
}


def _release_documents() -> list[str]:
    config_path = ROOT / "tools" / "release_documents.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    documents = list(config["required"])
    documents.extend(
        name for name in config.get("optional", []) if (ROOT / name).is_file()
    )
    return documents


def test_project_version_matches_runtime_version() -> None:
    assert read_project_version(ROOT / "pyproject.toml") == __version__


def test_project_version_rejects_missing_project_version(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'highlightminer-test'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="project.version"):
        read_project_version(pyproject)


def test_portable_runtime_staging_directories_are_tracked() -> None:
    assert (ROOT / "bin" / ".gitkeep").is_file()
    assert (ROOT / "runtime" / "cuda" / ".gitkeep").is_file()


def test_release_document_manifest_covers_required_documents() -> None:
    documents = _release_documents()

    assert REQUIRED_RELEASE_DOCUMENTS <= set(documents)
    assert len(documents) == len(set(documents))
    for name in documents:
        assert (ROOT / name).is_file(), f"Release document is missing: {name}"


def test_public_windows_ci_is_validation_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-windows-exe.yml").read_text(encoding="utf-8")

    assert "build_windows.ps1 -SkipZip" in workflow
    assert "actions/upload-artifact@" not in workflow
