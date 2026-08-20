from __future__ import annotations

from pathlib import Path

import pytest

from highlightminer import export


def _stub_runtime(monkeypatch, source_duration: float) -> None:
    monkeypatch.setattr(export, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(export, "require_executable", lambda _name: "ffmpeg")
    monkeypatch.setattr(export, "probe_media", lambda _path: {"duration": source_duration, "streams": []})
    monkeypatch.setattr(export, "has_encoder", lambda _name: False)


def test_preview_never_encodes_past_source_duration(monkeypatch, tmp_path: Path) -> None:
    duration = 15959.001859
    _stub_runtime(monkeypatch, duration)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    calls = []

    def fake_encode(_ffmpeg, _src, out, start, clip_duration, *, preview=False) -> None:
        calls.append((start, clip_duration, preview))
        out.write_bytes(b"preview")

    monkeypatch.setattr(export, "_run_h264_encode", fake_encode)

    export.create_preview_clip(source, tmp_path / "previews", "H001", 15958.0, 15959.002)

    assert calls == [(15958.0, duration - 15958.0, True)]


def test_export_repairs_reversed_range_before_encode(monkeypatch, tmp_path: Path) -> None:
    _stub_runtime(monkeypatch, 100.0)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    calls = []

    def fake_encode(_ffmpeg, _src, out, start, clip_duration, *, preview=False) -> None:
        calls.append((start, clip_duration, preview))
        out.write_bytes(b"export")

    monkeypatch.setattr(export, "_run_h264_encode", fake_encode)

    export.export_clip(source, tmp_path / "exports", "H001", 99.98, 99.0)

    start, clip_duration, preview = calls[0]
    assert 0.0 <= start < 100.0
    assert start + clip_duration <= 100.0
    assert clip_duration == pytest.approx(0.1)
    assert preview is False
