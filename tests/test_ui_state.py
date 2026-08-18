from highlightminer.config import Settings
from highlightminer.ui_common import (
    hydrate_persistent_widget,
    persist_widget_value,
    persisted_widget_key,
)
from highlightminer.ui_settings import (
    _ADVANCED_WHISPER_MODEL,
    _EDITOR_KEYS,
    _PRIMARY_WHISPER_MODELS,
    _editor_needs_seed,
    _model_editor_values,
)


def test_widget_backing_state_survives_streamlit_widget_cleanup() -> None:
    state: dict[str, object] = {}

    hydrate_persistent_widget(state, "video_path_input", "")
    state["video_path_input"] = r"D:\VODs\selected.mp4"
    persist_widget_value(state, "video_path_input")

    del state["video_path_input"]
    hydrate_persistent_widget(state, "video_path_input", "")

    assert state["video_path_input"] == r"D:\VODs\selected.mp4"
    assert state[persisted_widget_key("video_path_input")] == r"D:\VODs\selected.mp4"


def test_settings_editor_reseeds_when_streamlit_removed_a_widget_key() -> None:
    state = {
        key: "present"
        for name, key in _EDITOR_KEYS.items()
        if name != "custom_model"
    }
    state[_EDITOR_KEYS["model"]] = "large-v3"

    assert _editor_needs_seed(state) is False

    del state[_EDITOR_KEYS["audio_weight"]]
    assert _editor_needs_seed(state) is True


def test_advanced_model_selection_does_not_force_full_reseed() -> None:
    state = {
        key: "present"
        for name, key in _EDITOR_KEYS.items()
        if name != "custom_model"
    }
    state[_EDITOR_KEYS["model"]] = _ADVANCED_WHISPER_MODEL

    # The conditional custom-model text box does not exist until this choice is
    # rendered. Its absence must not reset the model selectbox to SQLite state.
    assert _editor_needs_seed(state) is False


def test_default_model_is_first_and_legacy_aliases_use_advanced_editor() -> None:
    assert _PRIMARY_WHISPER_MODELS[0] == "large-v3"
    assert _model_editor_values(Settings(whisper_model="large-v3")) == ("large-v3", "")
    assert _model_editor_values(Settings(whisper_model="base.en")) == (
        _ADVANCED_WHISPER_MODEL,
        "base.en",
    )
