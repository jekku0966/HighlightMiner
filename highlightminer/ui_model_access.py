from __future__ import annotations

from pathlib import Path

import streamlit as st

from .model_access import (
    ModelAccessPreferences,
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


def _sync_editor_with_persisted(preferences: ModelAccessPreferences) -> None:
    persisted = (preferences.download_consent, preferences.local_model_path or "")
    if st.session_state.get(_MODEL_ACCESS_SYNC_KEY) == persisted:
        return
    st.session_state[_CONSENT_EDITOR_KEY] = _CONSENT_LABELS.get(
        preferences.download_consent,
        _CONSENT_LABELS["unset"],
    )
    st.session_state[_LOCAL_MODEL_EDITOR_KEY] = preferences.local_model_path or ""
    st.session_state[_MODEL_ACCESS_SYNC_KEY] = persisted


def render_model_access_settings(db_path: Path) -> None:
    preferences = load_model_access(db_path)
    root = models_root()
    _sync_editor_with_persisted(preferences)

    st.subheader("Model access")
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
        f"A local model overrides the selected Hugging Face model and never needs a model download. "
        f"You can keep manually downloaded models under `{root}` or anywhere else on a local drive. "
        "Choose the actual CTranslate2 model folder containing config.json, model.bin, and tokenizer.json."
    )

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
            st.session_state[_CONSENT_EDITOR_KEY] = _CONSENT_LABELS[saved.download_consent]
            st.session_state[_LOCAL_MODEL_EDITOR_KEY] = saved.local_model_path or ""
            st.session_state[_MODEL_ACCESS_SYNC_KEY] = (
                saved.download_consent,
                saved.local_model_path or "",
            )
            st.success(
                "Model access saved. "
                + ("Local model selected." if saved.local_model_path else f"Download policy: {_CONSENT_LABELS[saved.download_consent]}.")
            )
        except Exception as exc:
            st.exception(exc)
