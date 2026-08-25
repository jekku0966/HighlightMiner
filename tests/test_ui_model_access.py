from __future__ import annotations

from highlightminer import ui_model_access
from highlightminer.model_access import ModelAccessPreferences


def test_saved_model_access_reload_does_not_mutate_live_widget_keys(monkeypatch) -> None:
    state = {
        ui_model_access._CONSENT_EDITOR_KEY: "Ask before any download",
        ui_model_access._LOCAL_MODEL_EDITOR_KEY: "C:/old-model",
        ui_model_access._MODEL_ACCESS_SYNC_KEY: ("unset", "C:/old-model"),
    }
    monkeypatch.setattr(ui_model_access.st, "session_state", state)

    saved = ModelAccessPreferences("deny", None)
    ui_model_access._queue_saved_editor_reload(saved)

    assert state[ui_model_access._CONSENT_EDITOR_KEY] == "Ask before any download"
    assert state[ui_model_access._LOCAL_MODEL_EDITOR_KEY] == "C:/old-model"
    assert ui_model_access._MODEL_ACCESS_SYNC_KEY not in state
    assert state[ui_model_access._MODEL_ACCESS_NOTICE_KEY] == "Model access saved. Download policy: Never download models."


def test_saved_model_access_resyncs_before_widgets_on_next_rerun(monkeypatch, tmp_path) -> None:
    state = {
        ui_model_access._CONSENT_EDITOR_KEY: "Ask before any download",
        ui_model_access._LOCAL_MODEL_EDITOR_KEY: "C:/old-model",
        ui_model_access._MODEL_ACCESS_SYNC_KEY: ("unset", "C:/old-model"),
    }
    saved = ModelAccessPreferences("deny", None)
    monkeypatch.setattr(ui_model_access.st, "session_state", state)
    ui_model_access._queue_saved_editor_reload(saved)

    widgets_started = False
    sync_called = False
    success_messages: list[str] = []
    original_sync = ui_model_access._sync_editor_with_persisted

    def tracked_sync(preferences: ModelAccessPreferences) -> None:
        nonlocal sync_called
        assert widgets_started is False
        sync_called = True
        original_sync(preferences)

    def fake_radio(_label, _labels, *, key, **_kwargs) -> None:
        nonlocal widgets_started
        widgets_started = True
        assert state[key] == "Never download models"

    def fake_path_picker(_label, key, **_kwargs) -> str:
        assert widgets_started is True
        assert state[key] == ""
        return state[key]

    monkeypatch.setattr(ui_model_access, "_sync_editor_with_persisted", tracked_sync)
    monkeypatch.setattr(ui_model_access, "load_model_access", lambda _db_path: saved)
    monkeypatch.setattr(ui_model_access, "models_root", lambda: tmp_path / "models")
    monkeypatch.setattr(ui_model_access, "huggingface_cache_directory", lambda: tmp_path / "cache")
    monkeypatch.setattr(ui_model_access, "path_picker", fake_path_picker)
    monkeypatch.setattr(ui_model_access.st, "subheader", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_model_access.st, "success", success_messages.append)
    monkeypatch.setattr(ui_model_access.st, "radio", fake_radio)
    monkeypatch.setattr(ui_model_access.st, "caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_model_access.st, "button", lambda *_args, **_kwargs: False)

    ui_model_access.render_model_access_settings(tmp_path / "highlightminer.db")

    assert sync_called is True
    assert state[ui_model_access._CONSENT_EDITOR_KEY] == "Never download models"
    assert state[ui_model_access._LOCAL_MODEL_EDITOR_KEY] == ""
    assert state[ui_model_access._MODEL_ACCESS_SYNC_KEY] == ("deny", "")
    assert ui_model_access._MODEL_ACCESS_NOTICE_KEY not in state
    assert success_messages == ["Model access saved. Download policy: Never download models."]
