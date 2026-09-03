from datetime import datetime, timezone
from pathlib import Path

from highlightminer import ui_mine
from highlightminer.analysis_jobs import (
    AnalysisJobStateError,
    AnalysisJobTerminalError,
    create_analysis_job,
    load_analysis_job,
    mark_analysis_job_awaiting_input,
    start_analysis_job,
)
from highlightminer.config import Settings
from highlightminer.model_access import (
    ModelAccessPreferences,
    ModelDecisionRequired,
    PreparedModelReference,
    load_model_access,
)
from highlightminer.storage import register_source
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
from highlightminer.ui_style import MODEL_ACCESS_CHOICES_KEY, model_access_choices_css


def test_widget_backing_state_survives_streamlit_widget_cleanup() -> None:
    state: dict[str, object] = {}

    hydrate_persistent_widget(state, "video_path_input", "")
    state["video_path_input"] = r"D:\VODs\selected.mp4"
    persist_widget_value(state, "video_path_input")

    del state["video_path_input"]
    hydrate_persistent_widget(state, "video_path_input", "")

    assert state["video_path_input"] == r"D:\VODs\selected.mp4"
    assert state[persisted_widget_key("video_path_input")] == r"D:\VODs\selected.mp4"


def test_exit_button_is_disabled_when_stopping_would_interrupt_work(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from streamlit.testing.v1 import AppTest

    shutdown_file = tmp_path / "shutdown.flag"
    monkeypatch.setenv("HIGHLIGHTMINER_SHUTDOWN_FILE", str(shutdown_file))
    app = AppTest.from_string(
        "from highlightminer.ui_common import render_shutdown\n"
        "render_shutdown(block_reason='Analysis is running.')\n"
    ).run(timeout=10)

    exit_button = next(button for button in app.button if button.label == "🛑 Exit HighlightMiner")
    assert exit_button.disabled is True
    assert any("Analysis is running." in caption.value for caption in app.caption)
    assert not shutdown_file.exists()


def test_settings_exit_uses_the_same_active_work_guard(monkeypatch, tmp_path: Path) -> None:
    from streamlit.testing.v1 import AppTest

    shutdown_file = tmp_path / "shutdown.flag"
    db_path = tmp_path / "highlightminer.db"
    monkeypatch.setenv("HIGHLIGHTMINER_SHUTDOWN_FILE", str(shutdown_file))
    app = AppTest.from_string(
        "from pathlib import Path\n"
        "import highlightminer.app as app\n"
        f"app.default_db_path = lambda: Path({str(db_path)!r})\n"
        "app.active_work_shutdown_block_reason = lambda _db: 'Export is running.'\n"
        "app._render_app()\n"
    ).run(timeout=10)

    app.radio[0].set_value("⚙️ Settings").run()

    exit_button = next(button for button in app.button if button.label == "🛑 Exit HighlightMiner")
    assert exit_button.disabled is True
    assert any("Export is running." in caption.value for caption in app.caption)


def test_load_latest_skips_newer_incompatible_analysis_formats() -> None:
    runs = [
        {"id": "future", "compatible": False},
        {"id": "latest-loadable", "compatible": True},
        {"id": "older", "compatible": True},
    ]

    assert ui_mine._latest_compatible_run(runs)["id"] == "latest-loadable"
    assert ui_mine._latest_compatible_run([runs[0]]) is None


def test_rerun_choice_stays_bound_to_the_original_vod(tmp_path: Path) -> None:
    original = tmp_path / "original.mp4"
    replacement = tmp_path / "replacement.mp4"
    pending = {"video_path": str(original.resolve())}

    assert ui_mine._rerun_source_matches_video(pending, str(original)) is True
    assert ui_mine._rerun_source_matches_video(pending, str(replacement)) is False
    assert ui_mine._rerun_source_matches_video(pending, "") is False


def test_rerun_model_warning_is_suppressed_for_cached_model(monkeypatch) -> None:
    settings = Settings(whisper_model="large-v3")
    access = ModelAccessPreferences(download_consent="deny")
    cached = PreparedModelReference(
        reference="cached-model",
        local_files_only=True,
        source="cache",
        display_name="large-v3",
    )
    monkeypatch.setattr(
        ui_mine,
        "resolve_model_reference",
        lambda actual_settings, actual_access: cached,
    )

    assert ui_mine._rerun_model_access_blocks_speech(settings, access) is False


def test_rerun_model_warning_is_shown_for_denied_uncached_model(monkeypatch) -> None:
    settings = Settings(whisper_model="large-v3")
    access = ModelAccessPreferences(download_consent="deny")
    monkeypatch.setattr(
        ui_mine,
        "resolve_model_reference",
        lambda actual_settings, actual_access: None,
    )

    assert ui_mine._rerun_model_access_blocks_speech(settings, access) is True


def test_rerun_model_warning_is_shown_for_stale_local_model(monkeypatch) -> None:
    settings = Settings(whisper_model="large-v3")
    access = ModelAccessPreferences(
        download_consent="deny",
        local_model_path="missing-local-model",
    )
    monkeypatch.setattr(
        ui_mine,
        "resolve_model_reference",
        lambda actual_settings, actual_access: (_ for _ in ()).throw(
            FileNotFoundError("model moved")
        ),
    )

    assert ui_mine._rerun_model_access_blocks_speech(settings, access) is True


def test_disabled_model_download_notice_explains_how_to_restore_speech() -> None:
    notice = ui_mine._transcription_skip_notice(
        {"status": "skipped", "reason": "model_downloads_disabled"}
    )

    assert "Never download models" in notice
    assert "Settings → Analysis engine → Model access" in notice
    assert "Force full reprocess" in notice


def test_requested_no_speech_notice_does_not_blame_model_access() -> None:
    notice = ui_mine._transcription_skip_notice(
        {"status": "skipped", "reason": "user_requested_no_transcription"}
    )

    assert "disabled for this run" in notice
    assert "Never download models" not in notice


def test_empty_source_keeps_analysis_action_disabled(monkeypatch, tmp_path: Path) -> None:
    state: dict[str, object] = {}
    buttons: list[tuple[str, bool]] = []
    captions: list[str] = []
    monkeypatch.setattr(ui_mine.st, "session_state", state)
    monkeypatch.setattr(
        ui_mine.st,
        "button",
        lambda label, **kwargs: buttons.append((label, bool(kwargs.get("disabled")))) or False,
    )
    monkeypatch.setattr(ui_mine.st, "caption", captions.append)

    ui_mine._render_analysis_controls(
        tmp_path / "highlightminer.db",
        "",
        "",
        "",
        "",
        "",
    )

    assert buttons == [("⛏️ Analyze VOD", True)]
    assert captions == ["Choose a VOD and work folder before starting analysis."]


def test_changing_source_clears_stale_rerun_choice(monkeypatch, tmp_path: Path) -> None:
    old_video = tmp_path / "old.mp4"
    new_video = tmp_path / "new.mp4"
    state = {
        ui_mine._PENDING_RERUN_KEY: {
            "video_path": str(old_video.resolve()),
            "source": {"id": "old-source"},
            "runs": [],
        }
    }
    notices: list[str] = []
    monkeypatch.setattr(ui_mine.st, "session_state", state)
    monkeypatch.setattr(ui_mine.st, "info", notices.append)
    monkeypatch.setattr(ui_mine.st, "button", lambda *_args, **_kwargs: False)

    ui_mine._render_analysis_controls(
        tmp_path / "highlightminer.db",
        str(new_video),
        "",
        "",
        "",
        str(tmp_path / "work"),
    )

    assert ui_mine._PENDING_RERUN_KEY not in state
    assert notices == ["The VOD selection changed, so the previous rerun choice was cleared."]


def test_analysis_deletion_requires_the_full_exact_id() -> None:
    analysis_id = "analysis-123"

    assert ui_mine._analysis_delete_confirmation_matches(analysis_id, analysis_id) is True
    assert ui_mine._analysis_delete_confirmation_matches(analysis_id, " analysis-123 ") is True
    assert ui_mine._analysis_delete_confirmation_matches(analysis_id, "analysis") is False
    assert ui_mine._analysis_delete_confirmation_matches(analysis_id, "") is False


def test_model_access_choice_row_has_scoped_equal_height_and_explicit_wrap() -> None:
    css = model_access_choices_css()

    assert f".st-key-{MODEL_ACCESS_CHOICES_KEY}" in css
    assert "height: 3.5rem" in css
    assert "flex-direction: row !important" in css
    assert "flex-wrap: nowrap" in css
    assert "flex: 0 0 12rem !important" in css
    assert "white-space: pre-line" in css
    assert ui_mine._CONTINUE_WITHOUT_SPEECH_LABEL.splitlines() == [
        "Continue without",
        "speech",
    ]


def test_candidate_table_formats_bounds_without_changing_review_values() -> None:
    analysis = {
        "candidates": [
            {
                "id": "H001",
                "rank": 1,
                "score": 0.9,
                "start": 10.0,
                "end": 20.0,
                "reason": "reaction",
            }
        ]
    }
    review = {
        "items": {
            "H001": {
                "status": "keep",
                "start": 12.0,
                "end": 20.5,
            }
        }
    }

    rows = ui_mine._candidate_rows(analysis, review)

    assert rows[0]["Start"] == "00:00:12"
    assert rows[0]["End"] == "00:00:20.5"
    assert review["items"]["H001"]["start"] == 12.0
    assert review["items"]["H001"]["end"] == 20.5


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


def _active_job(status: str = "queued") -> dict:
    return {
        "id": "job-123",
        "source_id": "source-123",
        "source_fingerprint": "fingerprint-123",
        "status": status,
        "stage": "queued",
        "message": "Analysis queued",
        "config": {
            "video_path": "/vod.mp4",
            "chat_path": None,
            "content_label": "Test",
            "analysis_title": "Snapshot title",
            "work_dir": "/work",
            "reuse_features": True,
        },
    }


def test_cancel_pending_job_distinguishes_terminal_state(monkeypatch, tmp_path: Path) -> None:
    completed = _active_job("completed")
    completed["analysis_id"] = "analysis-123"
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


def test_cancel_pending_job_preserves_ask_before_download_policy(tmp_path: Path) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    source = register_source(
        db,
        {
            "fingerprint": "source-fingerprint",
            "path": str(video),
            "video_name": video.name,
            "file_size": video.stat().st_size,
        },
    )
    job = create_analysis_job(db, source, {"settings": {}})
    start_analysis_job(db, job["id"])
    mark_analysis_job_awaiting_input(db, job["id"], message="Choose a model")

    outcome, _ = ui_mine._cancel_pending_analysis_job(db, job["id"])

    assert outcome == "cancelled"
    assert load_model_access(db).download_consent == "unset"


def test_cancel_cleanup_removes_pending_and_queued_worker_state(monkeypatch) -> None:
    state = {
        ui_mine._QUEUED_ANALYSIS_KEY: {"analysis_job_id": "job-123"},
        ui_mine._ANALYSIS_RUNNING_KEY: True,
        ui_mine._PENDING_MODEL_ANALYSIS_KEY: {"analysis_job_id": "job-123"},
        ui_mine._PENDING_RERUN_KEY: {"source": {"id": "source-123"}},
    }
    monkeypatch.setattr(ui_mine.st, "session_state", state)

    ui_mine._clear_pending_analysis_state()
    ui_mine._clear_queued_analysis_state()

    assert ui_mine._PENDING_MODEL_ANALYSIS_KEY not in state
    assert ui_mine._PENDING_RERUN_KEY not in state
    assert ui_mine._QUEUED_ANALYSIS_KEY not in state
    assert ui_mine._ANALYSIS_RUNNING_KEY not in state


def test_persistent_active_job_locks_controls_without_session_queue(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui_mine.st, "session_state", {})
    monkeypatch.setattr(ui_mine, "find_active_analysis_job", lambda _db: _active_job("running"))

    assert ui_mine.analysis_is_running(tmp_path / "highlightminer.db") is True


def test_queued_job_is_restored_after_streamlit_state_cleanup(monkeypatch, tmp_path: Path) -> None:
    state: dict[str, object] = {}
    monkeypatch.setattr(ui_mine.st, "session_state", state)
    monkeypatch.setattr(ui_mine, "find_active_analysis_job", lambda _db: _active_job())

    ui_mine._restore_persistent_analysis_state(tmp_path / "highlightminer.db")

    queued = state[ui_mine._QUEUED_ANALYSIS_KEY]
    assert queued["analysis_job_id"] == "job-123"
    assert queued["analysis_title"] == "Snapshot title"
    assert state[ui_mine._ANALYSIS_RUNNING_KEY] is True


def test_waiting_job_is_not_reprompted_while_model_decision_resume_is_queued(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = {
        ui_mine._QUEUED_ANALYSIS_KEY: {
            "analysis_job_id": "job-123",
            ui_mine._MODEL_DECISION_RESUME_KEY: True,
        },
        ui_mine._ANALYSIS_RUNNING_KEY: True,
    }
    monkeypatch.setattr(ui_mine.st, "session_state", state)
    monkeypatch.setattr(
        ui_mine,
        "find_active_analysis_job",
        lambda _db: _active_job("awaiting_input"),
    )

    ui_mine._restore_persistent_analysis_state(tmp_path / "highlightminer.db")

    assert ui_mine._PENDING_MODEL_ANALYSIS_KEY not in state


def test_model_decision_choices_resume_the_waiting_job(monkeypatch, tmp_path: Path) -> None:
    class SessionState(dict):
        __setattr__ = dict.__setitem__

    choices = [
        {"allow_model_download": True, "skip_transcription": False},
        {"allow_model_download": False, "skip_transcription": False},
        {"allow_model_download": False, "skip_transcription": True},
    ]

    for choice in choices:
        state = SessionState(
            {
                ui_mine._PENDING_MODEL_ANALYSIS_KEY: {
                    **ui_mine._job_analysis_args(_active_job("awaiting_input")),
                    "message": "Choose a model",
                },
            }
        )
        observed: dict[str, object] = {}
        monkeypatch.setattr(ui_mine.st, "session_state", state)
        monkeypatch.setattr(ui_mine.st, "rerun", lambda: None)
        monkeypatch.setattr(
            ui_mine,
            "load_analysis_job",
            lambda _db, _job: _active_job("awaiting_input"),
        )

        def run_analysis(**kwargs):
            observed.update(kwargs)
            return "analysis-123"

        monkeypatch.setattr(ui_mine, "_run_analysis_ui", run_analysis)

        ui_mine._resume_pending_model_analysis(
            tmp_path / "highlightminer.db",
            **choice,
        )
        assert state[ui_mine._QUEUED_ANALYSIS_KEY][ui_mine._MODEL_DECISION_RESUME_KEY] is True

        ui_mine._run_queued_analysis(tmp_path / "highlightminer.db")

        assert observed["analysis_job_id"] == "job-123"
        assert observed["allow_model_download"] is choice["allow_model_download"]
        assert observed["skip_transcription"] is choice["skip_transcription"]
        assert ui_mine._MODEL_DECISION_RESUME_KEY not in observed
        assert state["analysis_id"] == "analysis-123"
        assert ui_mine._PENDING_MODEL_ANALYSIS_KEY not in state
        assert ui_mine._QUEUED_ANALYSIS_KEY not in state
        assert ui_mine._ANALYSIS_RUNNING_KEY not in state


def test_rerun_does_not_launch_a_second_worker_for_running_job(monkeypatch, tmp_path: Path) -> None:
    state = {
        ui_mine._QUEUED_ANALYSIS_KEY: {"analysis_job_id": "job-123"},
        ui_mine._ANALYSIS_RUNNING_KEY: True,
    }
    monkeypatch.setattr(ui_mine.st, "session_state", state)
    monkeypatch.setattr(ui_mine, "load_analysis_job", lambda _db, _job: _active_job("running"))
    monkeypatch.setattr(
        ui_mine,
        "_run_analysis_ui",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("duplicate launch")),
    )

    ui_mine._run_queued_analysis(tmp_path / "highlightminer.db")

    assert ui_mine._QUEUED_ANALYSIS_KEY not in state
    assert ui_mine._ANALYSIS_RUNNING_KEY not in state


def test_start_race_reports_existing_worker_instead_of_failure(monkeypatch, tmp_path: Path) -> None:
    state = {
        ui_mine._QUEUED_ANALYSIS_KEY: {"analysis_job_id": "job-123"},
        ui_mine._ANALYSIS_RUNNING_KEY: True,
    }
    monkeypatch.setattr(ui_mine.st, "session_state", state)
    monkeypatch.setattr(ui_mine.st, "rerun", lambda: None)
    monkeypatch.setattr(
        ui_mine,
        "_run_analysis_ui",
        lambda **_kwargs: (_ for _ in ()).throw(
            AnalysisJobStateError("another session started this job")
        ),
    )
    observed_jobs = iter([_active_job("queued"), _active_job("running")])
    monkeypatch.setattr(ui_mine, "load_analysis_job", lambda _db, _job: next(observed_jobs))

    ui_mine._run_queued_analysis(tmp_path / "highlightminer.db")

    assert state["analysis_notice"] == "Analysis is already running in another session."
    assert "analysis_error" not in state
    assert ui_mine._QUEUED_ANALYSIS_KEY not in state
    assert ui_mine._ANALYSIS_RUNNING_KEY not in state


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
    assert ui_mine._ANALYSIS_RUNNING_KEY not in state


def test_model_prompt_self_clears_when_job_already_completed(monkeypatch, tmp_path: Path) -> None:
    state = {
        ui_mine._PENDING_MODEL_ANALYSIS_KEY: {"analysis_job_id": "job-123"},
        ui_mine._PENDING_RERUN_KEY: {"source": {"id": "source-123"}},
    }
    completed = _active_job("completed")
    completed["analysis_id"] = "analysis-123"
    monkeypatch.setattr(ui_mine.st, "session_state", state)
    monkeypatch.setattr(ui_mine.st, "rerun", lambda: None)
    monkeypatch.setattr(ui_mine, "load_analysis_job", lambda _db, _job: completed)

    assert ui_mine._render_model_decision(tmp_path / "highlightminer.db") is True

    assert state["analysis_id"] == "analysis-123"
    assert state["analysis_notice"] == "Analysis had already completed."
    assert ui_mine._PENDING_MODEL_ANALYSIS_KEY not in state
    assert ui_mine._PENDING_RERUN_KEY not in state


def test_job_timer_uses_persisted_start_and_finish_times() -> None:
    job = {
        "created_at": "2026-08-26T10:00:00+00:00",
        "started_at": "2026-08-26T10:00:05+00:00",
        "finished_at": None,
    }

    assert ui_mine._job_elapsed_seconds(
        job,
        now=datetime(2026, 8, 26, 10, 1, 10, tzinfo=timezone.utc),
    ) == 65.0
    assert ui_mine._format_elapsed(65.0) == "00:01:05"


def test_job_is_created_with_click_time_settings_snapshot(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "vod.mp4"
    video.write_bytes(b"video")
    db = tmp_path / "highlightminer.db"
    source = register_source(
        db,
        {
            "id": "ignored",
            "fingerprint": "source-fingerprint",
            "path": str(video),
            "video_name": video.name,
            "file_size": video.stat().st_size,
        },
    )
    monkeypatch.setattr(ui_mine, "load_app_settings", lambda _db: Settings(beam_size=7))

    job = ui_mine._create_queued_analysis_job(
        db,
        source=source,
        video_path=str(video),
        chat_path="",
        content_label="Test",
        analysis_title="  Immutable title  ",
        work_dir=str(tmp_path / "work"),
        reuse_features=True,
    )

    persisted = load_analysis_job(db, job["id"])
    assert persisted["status"] == "queued"
    assert persisted["config"]["settings"]["beam_size"] == 7
    assert persisted["config"]["analysis_title"] == "Immutable title"
