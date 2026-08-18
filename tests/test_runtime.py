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


def test_source_cuda_runtime_prefers_dedicated_directory(monkeypatch, tmp_path: Path) -> None:
    cuda_root = tmp_path / "runtime" / "cuda"
    cuda_root.mkdir(parents=True)
    for name in runtime.portable_cuda_core_dlls():
        (cuda_root / name).touch()

    monkeypatch.setattr(runtime, "app_root", lambda: tmp_path)
    monkeypatch.setattr(runtime, "is_frozen", lambda: False)

    assert runtime.portable_cuda_root() == cuda_root


def test_source_cuda_runtime_falls_back_to_app_root_when_incomplete(monkeypatch, tmp_path: Path) -> None:
    cuda_root = tmp_path / "runtime" / "cuda"
    cuda_root.mkdir(parents=True)
    (cuda_root / runtime.portable_cuda_core_dlls()[0]).touch()

    monkeypatch.setattr(runtime, "app_root", lambda: tmp_path)
    monkeypatch.setattr(runtime, "is_frozen", lambda: False)

    assert runtime.portable_cuda_root() == tmp_path
