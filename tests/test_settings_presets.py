from highlightminer.settings_presets import WEIGHT_PRESETS, preset_is_pending, preset_preview


def test_selected_preset_is_pending_until_editor_weights_match() -> None:
    assert not preset_is_pending("Balanced", WEIGHT_PRESETS["Balanced"])
    assert preset_is_pending("Audio-heavy", WEIGHT_PRESETS["Balanced"])
    assert not preset_is_pending("Custom", {"audio": 0.5, "transcript": 0.3, "chat": 0.2})


def test_pending_preset_accepts_tolerance_and_unknown_names() -> None:
    near_audio_heavy = {"audio": 0.599, "transcript": 0.25, "chat": 0.15}
    assert not preset_is_pending("Audio-heavy", near_audio_heavy)
    assert not preset_is_pending("Nonexistent", WEIGHT_PRESETS["Balanced"])


def test_preset_preview_exposes_selected_weights_before_apply() -> None:
    preview = preset_preview("Audio-heavy")
    assert preview == {"audio": 0.60, "transcript": 0.25, "chat": 0.15}
    assert preset_preview("Custom") is None
