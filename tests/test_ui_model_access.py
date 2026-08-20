from __future__ import annotations

from highlightminer.model_access import ModelAccessPreferences
from highlightminer import ui_model_access


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
