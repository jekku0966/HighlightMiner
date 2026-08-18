from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def read_project_version(path: str | Path = "pyproject.toml") -> str:
    pyproject = Path(path)
    with pyproject.open("rb") as handle:
        data: dict[str, Any] = tomllib.load(handle)

    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml does not contain a [project] table")

    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("pyproject.toml does not contain a valid project.version")
    return version.strip()


def main() -> None:
    print(read_project_version())


if __name__ == "__main__":
    main()
