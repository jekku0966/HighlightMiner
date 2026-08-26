from highlightminer import ui_mine
from highlightminer.analysis_jobs import AnalysisJobTerminalError
from highlightminer.config import Settings
from highlightminer.model_access import ModelDecisionRequired
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


def test_model_decision_keeps_persistent_job_identity(monkeypatch) -> None:
    state: dict[str, object] = {}
    monkeypatch.setattr(ui_mine.st, "session_state", state)
    error = ModelDecisionRequired("Choose a model")
    error.analysis_job_id = "job-123"

    ui_mine._queue_model_decision(error, video_path="vod.mp4")

    pending = state[ui_mine._PENDING_MODEL_ANALYSIS_KEY]
    assert pending["analysis_job_id"] == "job-123"
    assert pending["video_path"] == "vod.mp4"


def test_cancel_pending_job_distinguishes_terminal_state(monkeypatch, tmp_path) -> None:
    completed = {"status": "completed", "analysis_id": "analysis-123"}
    monkeypatch.setattr(ui_mine, "cancel_analysis_job", lambda _db, _job: False)
    monkeypatch.setattr(ui_mine, "load_analysis_job", lambda _db, _job: completed)

    outcome, job = ui_mine._cancel_pending_analysis_job(
        tmp_path / "highlightminer.db",
        "job-123",
    )

    assert outcome == "completed"
    assert job == completed


def test_cancel_pending_job_clears_missing_job(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        ui_mine,
        "cancel_analysis_job",
        lambda _db, _job: (_ for _ in ()).throw(KeyError("gone")),
    )

    outcome, job = ui_mine._cancel_pending_analysis_job(
        tmp_path / "highlightminer.db",
        "job-123",
    )

    assert outcome == "missing"
    assert job is None


def test_terminal_model_decision_race_does_not_leave_pending_prompt(monkeypatch, tmp_path) -> None:
    state = {
        ui_mine._QUEUED_ANALYSIS_KEY: {"video_path": "vod.mp4"},
        ui_mine._ANALYSIS_RUNNING_KEY: True,
        ui_mine._PENDING_MODEL_ANALYSIS_KEY: {"analysis_job_id": "job-123"},
        ui_mine._PENDING_RERUN_KEY: {"source": {"id": "source-123"}},
    }
    terminal = AnalysisJobTerminalError(
        {
            "id": "job-123",
            "status": "cancelled",
            "analysis_id": None,
            "message": "Analysis cancelled",
        }
    )
    monkeypatch.setattr(ui_mine.st, "session_state", state)
    monkeypatch.setattr(ui_mine.st, "rerun", lambda: None)

    def raise_terminal(**_kwargs):
        raise terminal

    monkeypatch.setattr(ui_mine, "_run_analysis_ui", raise_terminal)

    ui_mine._run_queued_analysis(tmp_path / "highlightminer.db")

    assert state["analysis_notice"] == "Analysis was cancelled."
    assert ui_mine._PENDING_MODEL_ANALYSIS_KEY not in state
    assert ui_mine._PENDING_RERUN_KEY not in state
    assert ui_mine._QUEUED_ANALYSIS_KEY not in state
