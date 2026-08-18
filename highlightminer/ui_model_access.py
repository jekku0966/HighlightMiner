from __future__ import annotations

from pathlib import Path

import streamlit as st

from .model_access import (
    ModelAccessPreferences,
    load_model_access,
    models_root,
    save_model_access,
    set_model_download_consent,
    validate_local_model_directory,
)
from .ui_common import path_picker

_CONSENT_LABELS = {
    "unset": "Ask before any download",
    "allow": "Allow model downloads",
    "deny": "Never download models",
}
_LABEL_TO_CONSENT = {label: value for value, label in _CONSENT_LABELS.items()}


def render_model_download_consent(db_path: Path) -> None:
    preferences = load_model_access(db_path)
    models_root()
    if preferences.download_consent != "unset" or preferences.local_model_path:
        return

    with st.container(border=True):
        st.subheader("Speech-recognition model download")
        st.write(
            "HighlightMiner uses faster-whisper for speech recognition. A selected model may need to be downloaded from Hugging Face before transcription. "
            "HighlightMiner will not download a recognition model unless you explicitly allow it."
        )
        st.caption(
            "You can say no and use an already cached model, or manually choose a local CTranslate2 Whisper model folder under Settings → Analysis engine. "
            "This choice is stored only in the local HighlightMiner database and can be changed later."
        )
        yes, no = st.columns(2)
        if yes.button("Allow model downloads", type="primary", width="stretch"):
            set_model_download_consent("allow", db_path)
            st.rerun()
        if no.button("No model downloads", width="stretch"):
            set_model_download_consent("deny", db_path)
            st.rerun()


def render_model_access_settings(db_path: Path) -> None:
    preferences = load_model_access(db_path)
    root = models_root()

    st.subheader("Model access")
    labels = list(_CONSENT_LABELS.values())
    current_label = _CONSENT_LABELS.get(preferences.download_consent, _CONSENT_LABELS["unset"])
    if "model_download_consent_editor" not in st.session_state:
        st.session_state["model_download_consent_editor"] = current_label
    st.radio(
        "Recognition-model downloads",
        labels,
        key="model_download_consent_editor",
        help="This permission is local to this HighlightMiner database. Imported settings files cannot grant download permission.",
    )

    local_path = path_picker(
        "Local Whisper model folder (optional)",
        "local_whisper_model_path_editor",
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
            consent = _LABEL_TO_CONSENT[str(st.session_state["model_download_consent_editor"])]
            saved = save_model_access(
                ModelAccessPreferences(consent, local_path or None),
                db_path,
            )
            st.success(
                "Model access saved. "
                + ("Local model selected." if saved.local_model_path else f"Download policy: {_CONSENT_LABELS[saved.download_consent]}.")
            )
        except Exception as exc:
            st.exception(exc)
