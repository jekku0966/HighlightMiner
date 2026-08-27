from highlightminer import ui_settings
from highlightminer.settings_presets import WEIGHT_PRESETS


def _editor_state(*, preset: str, weights: dict[str, float]) -> dict[str, object]:
    keys = ui_settings._EDITOR_KEYS
    return {
        keys["preset"]: preset,
        keys["audio_weight"]: weights["audio"],
        keys["transcript_weight"]: weights["transcript"],
        keys["chat_weight"]: weights["chat"],
    }


def test_selecting_preset_immediately_fills_weight_editor_without_saving(monkeypatch) -> None:
    state = _editor_state(preset="Audio-heavy", weights=WEIGHT_PRESETS["Balanced"])
    monkeypatch.setattr(ui_settings.st, "session_state", state)
    monkeypatch.setattr(
        ui_settings,
        "save_app_settings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("preset selection persisted")),
    )

    ui_settings._apply_selected_preset()

    keys = ui_settings._EDITOR_KEYS
    assert state[keys["audio_weight"]] == 0.60
    assert state[keys["transcript_weight"]] == 0.25
    assert state[keys["chat_weight"]] == 0.15


def test_manual_weight_edit_updates_preset_selector(monkeypatch) -> None:
    state = _editor_state(
        preset="Audio-heavy",
        weights={"audio": 0.5, "transcript": 0.3, "chat": 0.2},
    )
    monkeypatch.setattr(ui_settings.st, "session_state", state)

    ui_settings._sync_preset_to_weights()

    assert state[ui_settings._EDITOR_KEYS["preset"]] == "Custom"


def test_manual_weights_that_match_preset_restore_its_name(monkeypatch) -> None:
    state = _editor_state(preset="Custom", weights=WEIGHT_PRESETS["Reaction-heavy"])
    monkeypatch.setattr(ui_settings.st, "session_state", state)

    ui_settings._sync_preset_to_weights()

    assert state[ui_settings._EDITOR_KEYS["preset"]] == "Reaction-heavy"
