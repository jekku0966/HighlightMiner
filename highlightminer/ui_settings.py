from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import streamlit as st

from .config import Settings, _STANDARD_WHISPER_MODELS
from .runtime import app_root
from .settings_presets import WEIGHT_PRESETS, detect_weight_preset, normalize_weights
from .settings_store import export_app_settings, import_app_settings, load_app_settings, reset_app_settings, save_app_settings
from .ui_common import _JSON_FILTER, choose_save_file, path_picker
from .ui_model_access import render_model_access_settings

_EDITOR_KEYS = {
    "model": "cfg_model",
    "custom_model": "cfg_custom_model",
    "device": "cfg_device",
    "compute": "cfg_compute",
    "language": "cfg_language",
    "beam": "cfg_beam",
    "vad": "cfg_vad",
    "audio_window": "cfg_audio_window",
    "audio_hop": "cfg_audio_hop",
    "pre_roll": "cfg_pre_roll",
    "post_roll": "cfg_post_roll",
    "merge_gap": "cfg_merge_gap",
    "max_clip": "cfg_max_clip",
    "min_score": "cfg_min_score",
    "max_candidates": "cfg_max_candidates",
    "audio_weight": "cfg_audio_weight",
    "transcript_weight": "cfg_transcript_weight",
    "chat_weight": "cfg_chat_weight",
    "reactions": "cfg_reactions",
    "preset": "cfg_preset",
}

_PRIMARY_WHISPER_MODELS = ("large-v3", "turbo", "medium", "small")
_ADVANCED_WHISPER_MODEL = "Other / advanced…"


def _model_editor_values(settings: Settings) -> tuple[str, str]:
    if settings.whisper_model in _PRIMARY_WHISPER_MODELS:
        return settings.whisper_model, ""
    return _ADVANCED_WHISPER_MODEL, settings.whisper_model


def _editor_needs_seed(state: Mapping[str, Any]) -> bool:
    # Only always-rendered widgets decide whether the editor was cleaned up by
    # Streamlit. The advanced model-name field is conditional: requiring it here
    # would snap a freshly selected "Other / advanced…" choice back to the saved
    # model before the text field has had a chance to render.
    required_names = [name for name in _EDITOR_KEYS if name != "custom_model"]
    return any(_EDITOR_KEYS[name] not in state for name in required_names)


def _seed_editor(settings: Settings, *, force: bool = False) -> None:
    if not force and not _editor_needs_seed(st.session_state):
        return
    normalized = normalize_weights(settings.weights)
    model, custom_model = _model_editor_values(settings)
    values = {
        "model": model,
        "custom_model": custom_model,
        "device": settings.device,
        "compute": settings.compute_type,
        "language": settings.language or "",
        "beam": int(settings.beam_size),
        "vad": bool(settings.vad_filter),
        "audio_window": float(settings.audio_window_sec),
        "audio_hop": float(settings.audio_hop_sec),
        "pre_roll": float(settings.pre_roll_sec),
        "post_roll": float(settings.post_roll_sec),
        "merge_gap": float(settings.merge_gap_sec),
        "max_clip": float(settings.max_candidate_sec),
        "min_score": float(settings.min_candidate_score),
        "max_candidates": int(settings.max_candidates),
        "audio_weight": normalized["audio"],
        "transcript_weight": normalized["transcript"],
        "chat_weight": normalized["chat"],
        "reactions": "\n".join(settings.reaction_phrases),
        "preset": detect_weight_preset(normalized),
    }
    for name, value in values.items():
        st.session_state[_EDITOR_KEYS[name]] = value


def _request_reload(message: str) -> None:
    st.session_state["settings_editor_reload"] = True
    st.session_state["settings_notice"] = message


def _apply_preset() -> None:
    preset = st.session_state.get(_EDITOR_KEYS["preset"], "Balanced")
    if preset not in WEIGHT_PRESETS:
        return
    values = WEIGHT_PRESETS[preset]
    st.session_state[_EDITOR_KEYS["audio_weight"]] = values["audio"]
    st.session_state[_EDITOR_KEYS["transcript_weight"]] = values["transcript"]
    st.session_state[_EDITOR_KEYS["chat_weight"]] = values["chat"]


def _browse_export() -> None:
    try:
        current = st.session_state.get("settings_export_path", str(app_root() / "HighlightMiner-settings.json"))
        selected = choose_save_file("Export HighlightMiner settings", current)
        if selected:
            st.session_state["settings_export_path"] = selected
    except Exception as exc:
        st.session_state["native_dialog_error"] = str(exc)


def _build_settings() -> Settings:
    model_choice = str(st.session_state[_EDITOR_KEYS["model"]])
    advanced = model_choice == _ADVANCED_WHISPER_MODEL
    model = str(st.session_state.get(_EDITOR_KEYS["custom_model"], "")).strip() if advanced else model_choice
    phrases = [line.strip() for line in str(st.session_state[_EDITOR_KEYS["reactions"]]).splitlines() if line.strip()]
    return Settings(
        whisper_model=model,
        allow_custom_whisper_model=bool(advanced and model not in _STANDARD_WHISPER_MODELS),
        device=str(st.session_state[_EDITOR_KEYS["device"]]),
        compute_type=str(st.session_state[_EDITOR_KEYS["compute"]]),
        language=str(st.session_state[_EDITOR_KEYS["language"]]).strip() or None,
        beam_size=int(st.session_state[_EDITOR_KEYS["beam"]]),
        vad_filter=bool(st.session_state[_EDITOR_KEYS["vad"]]),
        audio_window_sec=float(st.session_state[_EDITOR_KEYS["audio_window"]]),
        audio_hop_sec=float(st.session_state[_EDITOR_KEYS["audio_hop"]]),
        pre_roll_sec=float(st.session_state[_EDITOR_KEYS["pre_roll"]]),
        post_roll_sec=float(st.session_state[_EDITOR_KEYS["post_roll"]]),
        merge_gap_sec=float(st.session_state[_EDITOR_KEYS["merge_gap"]]),
        max_candidate_sec=float(st.session_state[_EDITOR_KEYS["max_clip"]]),
        min_candidate_score=float(st.session_state[_EDITOR_KEYS["min_score"]]),
        max_candidates=int(st.session_state[_EDITOR_KEYS["max_candidates"]]),
        weights={
            "audio": float(st.session_state[_EDITOR_KEYS["audio_weight"]]),
            "transcript": float(st.session_state[_EDITOR_KEYS["transcript_weight"]]),
            "chat": float(st.session_state[_EDITOR_KEYS["chat_weight"]]),
        },
        reaction_phrases=phrases,
    )


def render_settings_page(db_path: Path) -> None:
    settings = load_app_settings(db_path)
    if st.session_state.pop("settings_editor_reload", False):
        _seed_editor(settings, force=True)
    else:
        _seed_editor(settings)

    st.header("⚙️ Settings")
    st.caption("These settings are stored in highlightminer.db and apply to future analyses and reruns. Existing analysis runs keep their original settings snapshot.")
    notice = st.session_state.pop("settings_notice", None)
    if notice:
        st.success(notice)

    engine, detection, reactions, transfer = st.tabs(["Analysis engine", "Detection & weights", "Reaction phrases", "Import / Export"])

    with engine:
        render_model_access_settings(db_path)
        st.divider()
        st.selectbox(
            "Whisper model",
            list(_PRIMARY_WHISPER_MODELS) + [_ADVANCED_WHISPER_MODEL],
            key=_EDITOR_KEYS["model"],
            help="large-v3 is HighlightMiner's default. Turbo is the faster general-purpose option. Use Other / advanced only when you deliberately want a different standard alias or custom Hugging Face model.",
        )
        if st.session_state[_EDITOR_KEYS["model"]] == _ADVANCED_WHISPER_MODEL:
            if _EDITOR_KEYS["custom_model"] not in st.session_state:
                st.session_state[_EDITOR_KEYS["custom_model"]] = ""
            st.text_input(
                "Other model name",
                key=_EDITOR_KEYS["custom_model"],
                placeholder="e.g. base.en or organization/model-name",
                help="Advanced opt-in. Standard faster-whisper aliases remain standard; arbitrary repositories are treated as custom models. A network download still requires the separate permission above.",
            )
        c1, c2 = st.columns(2)
        with c1:
            st.selectbox("Device", ["auto", "cuda", "cpu"], key=_EDITOR_KEYS["device"])
            st.number_input("Beam size", min_value=1, max_value=20, step=1, key=_EDITOR_KEYS["beam"])
        with c2:
            st.selectbox("Compute type", ["auto", "float16", "float32", "int8", "int8_float16", "int8_float32", "bfloat16"], key=_EDITOR_KEYS["compute"])
            st.text_input("Language", key=_EDITOR_KEYS["language"], placeholder="blank = auto detect")
        st.checkbox("VAD filtering", key=_EDITOR_KEYS["vad"], help="Voice activity detection can skip long non-speech regions during transcription.")

    with detection:
        p1, p2 = st.columns([3, 1], vertical_alignment="bottom")
        with p1:
            st.selectbox("Signal weighting preset", list(WEIGHT_PRESETS) + ["Custom"], key=_EDITOR_KEYS["preset"], help="Presets change signal weights only.")
        with p2:
            st.button("Apply preset", width="stretch", disabled=st.session_state[_EDITOR_KEYS["preset"]] == "Custom", on_click=_apply_preset)

        st.slider("Audio weight", 0.0, 1.0, step=0.01, key=_EDITOR_KEYS["audio_weight"])
        st.slider("Transcript / reaction weight", 0.0, 1.0, step=0.01, key=_EDITOR_KEYS["transcript_weight"])
        st.slider("Chat weight", 0.0, 1.0, step=0.01, key=_EDITOR_KEYS["chat_weight"])
        raw_weights = {
            "audio": st.session_state[_EDITOR_KEYS["audio_weight"]],
            "transcript": st.session_state[_EDITOR_KEYS["transcript_weight"]],
            "chat": st.session_state[_EDITOR_KEYS["chat_weight"]],
        }
        if sum(raw_weights.values()) > 0:
            effective = normalize_weights(raw_weights)
            m1, m2, m3 = st.columns(3)
            m1.metric("Effective audio", f"{effective['audio']:.1%}")
            m2.metric("Effective transcript", f"{effective['transcript']:.1%}")
            m3.metric("Effective chat", f"{effective['chat']:.1%}")
            st.caption(
                f"Current weighting matches: **{detect_weight_preset(raw_weights)}**. "
                "If transcript or chat is unavailable during a run, that signal becomes 0% and the available signals are renormalized automatically."
            )
        else:
            st.error("At least one signal weight must be greater than zero.")

        c1, c2 = st.columns(2)
        with c1:
            st.slider("Minimum candidate score", 0.0, 1.0, step=0.01, key=_EDITOR_KEYS["min_score"])
            st.number_input("Maximum candidates", min_value=1, max_value=500, step=1, key=_EDITOR_KEYS["max_candidates"])
            st.number_input("Pre-roll (seconds)", min_value=0.0, max_value=600.0, step=1.0, key=_EDITOR_KEYS["pre_roll"])
            st.number_input("Post-roll (seconds)", min_value=0.0, max_value=600.0, step=1.0, key=_EDITOR_KEYS["post_roll"])
        with c2:
            st.number_input("Merge gap (seconds)", min_value=0.0, max_value=600.0, step=1.0, key=_EDITOR_KEYS["merge_gap"])
            st.number_input("Maximum clip length (seconds)", min_value=1.0, max_value=1800.0, step=1.0, key=_EDITOR_KEYS["max_clip"])
            st.number_input("Audio window (seconds)", min_value=0.1, max_value=10.0, step=0.1, key=_EDITOR_KEYS["audio_window"])
            st.number_input("Audio hop (seconds)", min_value=0.05, max_value=5.0, step=0.05, key=_EDITOR_KEYS["audio_hop"])

    with reactions:
        st.caption("One phrase per line. These phrases score transcript reactions; changing them can reuse an existing Whisper transcript and simply rescore its text.")
        st.text_area("Reaction phrases", height=420, key=_EDITOR_KEYS["reactions"])

    with transfer:
        st.subheader("Import")
        import_path = path_picker("Settings JSON", "settings_import_path", file_filter=_JSON_FILTER)
        if st.button("Import settings", disabled=not import_path):
            try:
                import_app_settings(import_path, db_path)
                _request_reload("Settings imported into the database. Model download permission and local model selection were not changed.")
                st.rerun()
            except Exception as exc:
                st.exception(exc)

        st.subheader("Export")
        if "settings_export_path" not in st.session_state:
            st.session_state["settings_export_path"] = str(app_root() / "HighlightMiner-settings.json")
        e1, e2 = st.columns([4, 1], vertical_alignment="bottom")
        with e1:
            st.text_input("Export destination", key="settings_export_path")
        with e2:
            st.button("Browse", width="stretch", on_click=_browse_export)
        if st.button("Export settings"):
            try:
                destination = export_app_settings(st.session_state["settings_export_path"], db_path)
                st.success(f"Exported to {destination}. Model download permission and local model selection are intentionally not exported.")
            except Exception as exc:
                st.exception(exc)

    st.divider()
    s1, s2 = st.columns([3, 1])
    with s1:
        if st.button("💾 Save settings", type="primary", width="stretch"):
            try:
                saved = save_app_settings(_build_settings(), db_path)
                _request_reload(f"Settings saved. Weight profile: {detect_weight_preset(saved.weights)}.")
                st.rerun()
            except Exception as exc:
                st.exception(exc)
    with s2:
        if st.button("Reset defaults", width="stretch"):
            reset_app_settings(db_path)
            _request_reload("Settings reset to HighlightMiner defaults. Model download permission and local model selection were left unchanged.")
            st.rerun()
