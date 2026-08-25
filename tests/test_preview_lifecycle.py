from __future__ import annotations

import os
from pathlib import Path

from highlightminer import export


def _stub_preview_runtime(monkeypatch) -> None:
    monkeypatch.setattr(export, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(export, "require_executable", lambda _name: "ffmpeg")


def test_preview_replacement_keeps_previous_file_until_encode_finishes(monkeypatch, tmp_path: Path) -> None:
    _stub_preview_runtime(monkeypatch)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    preview_dir = tmp_path / "previews"
    preview_dir.mkdir()
    previous = preview_dir / "H001_1_000_2_000.mp4"
    previous.write_bytes(b"old")

    observed_previous_state: list[bool] = []

    def fake_encode(_ffmpeg, _src, out, _start, _duration, *, preview=False) -> None:
        assert preview is True
        observed_previous_state.append(previous.exists())
        out.write_bytes(b"new")

    monkeypatch.setattr(export, "_run_h264_encode", fake_encode)

    result = export.create_preview_clip(source, preview_dir, "H001", 3.0, 4.0)

    assert observed_previous_state == [True]
    assert result.path.read_bytes() == b"new"
    assert result.cleanup_failures == 0


def test_preview_pruning_does_not_fail_when_windows_keeps_old_file_locked(monkeypatch, tmp_path: Path) -> None:
    preview_dir = tmp_path / "previews"
    preview_dir.mkdir()
    paths = []
    for index in range(6):
        path = preview_dir / f"H001_{index}.mp4"
        path.write_bytes(str(index).encode())
        os.utime(path, (index + 1, index + 1))
        paths.append(path)

    current = paths[-1]
    locked = paths[0]
    original_unlink = Path.unlink

    def flaky_unlink(self: Path, *args, **kwargs) -> None:
        if self == locked:
            raise PermissionError(32, "file is in use", str(self))
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    monkeypatch.setattr(export, "_PREVIEW_CLEANUP_DELAY_SEC", 0.0)

    cleanup_failures = export._prune_preview_files(preview_dir, "H001", keep_path=current)

    assert current.exists()
    assert locked.exists()
    assert cleanup_failures == 1
    assert len(list(preview_dir.glob("H001_*.mp4"))) <= export._PREVIEW_CACHE_KEEP + 1


def test_preview_returns_locked_cleanup_count_with_successful_replacement(monkeypatch, tmp_path: Path) -> None:
    _stub_preview_runtime(monkeypatch)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    preview_dir = tmp_path / "previews"
    preview_dir.mkdir()
    for index in range(export._PREVIEW_CACHE_KEEP):
        old_preview = preview_dir / f"H001_{index}.mp4"
        old_preview.write_bytes(b"old")
        os.utime(old_preview, (index + 1, index + 1))

    def fake_encode(_ffmpeg, _src, out, _start, _duration, *, preview=False) -> None:
        assert preview is True
        out.write_bytes(b"new")

    monkeypatch.setattr(export, "_run_h264_encode", fake_encode)
    monkeypatch.setattr(export, "_retry_unlink", lambda _path: False)

    result = export.create_preview_clip(source, preview_dir, "H001", 10.0, 12.0)

    assert result.path.read_bytes() == b"new"
    assert result.cleanup_failures == 1
