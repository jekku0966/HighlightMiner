from pathlib import Path

import highlightminer.export as export_module
from highlightminer.categorization import content_folder_name, normalize_content_label


def test_content_label_defaults_to_unsorted() -> None:
    assert normalize_content_label(None) == "Unsorted"
    assert normalize_content_label("   ") == "Unsorted"


def test_content_label_collapses_whitespace() -> None:
    assert normalize_content_label("  Just   Chatting  ") == "Just Chatting"


def test_content_folder_name_keeps_readable_unicode() -> None:
    assert content_folder_name("Alan Wake 2 – Yö") == "Alan Wake 2 – Yö"


def test_content_folder_name_replaces_windows_invalid_characters() -> None:
    assert content_folder_name('Game: Episode/One?') == "Game_ Episode_One_"


def test_content_folder_name_avoids_reserved_windows_names() -> None:
    assert content_folder_name("CON") == "CON_"
    assert content_folder_name("LPT1.txt") == "LPT1.txt_"


def test_export_clip_uses_content_subfolder(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"source")

    monkeypatch.setattr(export_module, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(export_module, "require_executable", lambda _: "ffmpeg")
    monkeypatch.setattr(export_module, "probe_media", lambda _path: {"duration": 120.0})

    def fake_encode(ffmpeg, src, out, start, duration, *, preview=False):
        out.write_bytes(b"clip")

    monkeypatch.setattr(export_module, "_run_h264_encode", fake_encode)

    out = export_module.export_clip(
        source,
        tmp_path / "clips",
        "H001",
        10.0,
        20.0,
        "nice play",
        category="Overwatch 2",
    )

    assert out == tmp_path / "clips" / "Overwatch 2" / "H001_nice_play.mp4"
    assert out.read_bytes() == b"clip"
