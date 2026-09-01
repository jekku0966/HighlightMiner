from __future__ import annotations

from pathlib import Path

import streamlit as st

from .model_access import (
    ModelAccessPreferences,
    huggingface_cache_directory,
    load_model_access,
    models_root,
    save_model_access,
    validate_local_model_directory,
)
from .ui_common import path_picker

_CONSENT_LABELS = {
    "unset": "Ask before any download",
    "allow": "Allow model downloads",
    "deny": "Never download models",
}
_LABEL_TO_CONSENT = {label: value for value, label in _CONSENT_LABELS.items()}
_CONSENT_EDITOR_KEY = "model_download_consent_editor"
_LOCAL_MODEL_EDITOR_KEY = "local_whisper_model_path_editor"
_MODEL_ACCESS_SYNC_KEY = "model_access_editor_persisted_value"
_MODEL_ACCESS_NOTICE_KEY = "model_access_notice"


def _sync_editor_with_persisted(preferences: ModelAccessPreferences) -> None:
    persisted = (preferences.download_consent, preferences.local_model_path or "")
    editor_present = (
        _CONSENT_EDITOR_KEY in st.session_state
        and _LOCAL_MODEL_EDITOR_KEY in st.session_state
    )
    if st.session_state.get(_MODEL_ACCESS_SYNC_KEY) == persisted and editor_present:
        return
    st.session_state[_CONSENT_EDITOR_KEY] = _CONSENT_LABELS.get(
        preferences.download_consent,
        _CONSENT_LABELS["unset"],
    )
    st.session_state[_LOCAL_MODEL_EDITOR_KEY] = preferences.local_model_path or ""
    st.session_state[_MODEL_ACCESS_SYNC_KEY] = persisted


def _queue_saved_editor_reload(saved: ModelAccessPreferences) -> None:
    """Request a safe next-rerun resync without mutating live widget-owned keys."""
    st.session_state.pop(_MODEL_ACCESS_SYNC_KEY, None)
    st.session_state[_MODEL_ACCESS_NOTICE_KEY] = (
        "Model access saved. "
        + (
            "Local model selected."
            if saved.local_model_path
            else f"Download policy: {_CONSENT_LABELS[saved.download_consent]}."
        )
    )


def render_model_access_settings(db_path: Path) -> None:
    preferences = load_model_access(db_path)
    root = models_root()
    cache_root = huggingface_cache_directory()
    _sync_editor_with_persisted(preferences)

    st.subheader("Model access", anchor=False)
    st.caption(
        "Download permission and local-model selection are local security controls. "
        "Save them here separately from the analysis settings below."
    )
    notice = st.session_state.pop(_MODEL_ACCESS_NOTICE_KEY, None)
    if notice:
        st.success(notice)

    labels = list(_CONSENT_LABELS.values())
    st.radio(
        "Recognition-model downloads",
        labels,
        key=_CONSENT_EDITOR_KEY,
        help=(
            "This permission is local to this HighlightMiner database. Imported settings files cannot grant download permission. "
            "Ask means HighlightMiner prompts only when a fresh transcript actually needs an uncached model."
        ),
    )

    local_path = path_picker(
        "Local Whisper model folder (optional)",
        _LOCAL_MODEL_EDITOR_KEY,
        default=preferences.local_model_path or "",
        placeholder=str(root / "your-model-folder"),
        folder=True,
    )
    st.caption(
        "This field is only for a model you add manually. Choose the actual CTranslate2 model folder containing "
        "config.json, model.bin, and tokenizer.json."
    )
    st.caption(f"Manual models folder: `{root}` — it is normal for this folder to be empty until you add a model yourself.")
    st.caption(f"Downloaded-model cache: `{cache_root}` — models fetched by faster-whisper/Hugging Face are stored here instead of the manual models folder.")

    if local_path:
        try:
            validated = validate_local_model_directory(local_path)
            st.success(f"Local model ready: {validated}")
        except Exception as exc:
            st.warning(str(exc))

    if st.button("Save model access", width="stretch"):
        try:
            consent = _LABEL_TO_CONSENT[str(st.session_state[_CONSENT_EDITOR_KEY])]
            saved = save_model_access(
                ModelAccessPreferences(consent, local_path or None),
                db_path,
            )
            _queue_saved_editor_reload(saved)
            st.rerun()
        except Exception as exc:
            st.exception(exc)
