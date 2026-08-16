from pathlib import Path

from highlightminer import runtime


def test_app_root_source_points_to_repository() -> None:
    expected = Path(runtime.__file__).resolve().parent.parent
    assert runtime.app_root() == expected


def test_app_root_uses_executable_when_frozen(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "HighlightMiner.exe"
    monkeypatch.setattr(runtime.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime.sys, "executable", str(exe))

    assert runtime.app_root() == tmp_path


def test_bundle_root_uses_meipass_when_frozen(monkeypatch, tmp_path: Path) -> None:
    bundle = tmp_path / "_internal"
    monkeypatch.setattr(runtime.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime.sys, "_MEIPASS", str(bundle), raising=False)

    assert runtime.bundle_root() == bundle
    assert runtime.bundled_path("highlightminer", "app.py") == bundle / "highlightminer" / "app.py"
