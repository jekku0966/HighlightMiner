from __future__ import annotations

from pathlib import Path

import streamlit as st

from .analysis_identity import load_analysis_identities, load_analysis_identity, save_analysis_title
from .categorization import normalize_content_label
from .export import create_preview_clip, export_clip
from .model_access import (
    ModelAccessPreferences,
    ModelDecisionRequired,
    huggingface_cache_directory,
    load_model_access,
    models_root,
    save_model_access,
    set_model_download_consent,
    validate_local_model_directory,
)
from .pipeline import analyze_vod
from .review import load_review, save_review
from .security import validate_local_video
from .settings_presets import detect_weight_preset, normalize_weights
from .settings_store import load_app_settings
from .storage import find_source_runs, import_legacy_analysis, learning_summary, list_analyses, load_analysis, record_export
from .transcription_status import is_transcription_skipped
from .ui_common import (
    _CHAT_FILTER,
    _JSON_FILTER,
    _VIDEO_FILTER,
    choose_folder,
    default_work_dir,
    path_picker,
    persistent_text_input,
    render_shutdown,
)
from .util import format_time

_PENDING_MODEL_ANALYSIS_KEY = "pending_model_analysis"
_PENDING_RERUN_KEY = "pending_rerun"
_QUEUED_ANALYSIS_KEY = "queued_analysis"
_ANALYSIS_RUNNING_KEY = "analysis_running"


def analysis_is_running() -> bool:
    """True while this Streamlit session owns a queued analysis run."""
    return bool(
        st.session_state.get(_ANALYSIS_RUNNING_KEY)
        and st.session_state.get(_QUEUED_ANALYSIS_KEY)
    )


def _queue_analysis(**analysis_args) -> None:
    st.session_state[_QUEUED_ANALYSIS_KEY] = dict(analysis_args)
    st.session_state[_ANALYSIS_RUNNING_KEY] = True


def _clear_queued_analysis_state() -> None:
    st.session_state.pop(_QUEUED_ANALYSIS_KEY, None)
    st.session_state.pop(_ANALYSIS_RUNNING_KEY, None)


def _clear_pending_analysis_state() -> None:
    """Clear transient state for an analysis attempt without unloading history."""
    st.session_state.pop(_PENDING_MODEL_ANALYSIS_KEY, None)
    st.session_state.pop(_PENDING_RERUN_KEY, None)


def _candidate_rows(analysis: dict, review: dict) -> list[dict]:
    rows = []
    for candidate in analysis.get("candidates", []):
        item = review["items"].get(candidate["id"], {})
        rows.append({
            "#": candidate["rank"],
            "ID": candidate["id"],
            "Score": round(candidate["score"] * 10, 1),
            "Start": format_time(item.get("start", candidate["start"])),
            "End": format_time(item.get("end", candidate["end"])),
            "Why": candidate["reason"],
            "Status": item.get("status", "unreviewed"),
        })
    return rows


def _history_label(row: dict, identity: dict[str, str]) -> str:
    created = str(row.get("created_at", "")).replace("T", " ").replace("+00:00", " UTC")
    title = identity.get("analysis_title", "").strip()
    title_text = f" · {title}" if title else ""
    return (
        f"{identity.get('analysis_name', 'Custom')}{title_text} · {row['content_label']} · "
        f"{row['video_name']} · run {row.get('run_number', 1)} · {created} · "
        f"{row['candidates']} candidates · {row['kept']} kept"
    )


def _run_analysis_ui(
    *,
    db_path: Path,
    video_path: str,
    chat_path: str,
    content_label: str,
    analysis_title: str,
    work_dir: str,
    source_info: dict | None = None,
    reuse_features: bool = True,
    allow_model_download: bool = False,
    skip_transcription: bool = False,
) -> str:
    settings = load_app_settings(db_path)
    with st.status("Analyzing…", expanded=True) as status:
        label = st.empty()
        bar = st.progress(0.0)

        def progress(message: str, value: float) -> None:
            label.write(message)
            bar.progress(min(1.0, max(0.0, value)))

        analysis_id = analyze_vod(
            video_path,
            work_dir,
            settings,
            chat_path or None,
            progress,
            content_label=content_label,
            db_path=db_path,
            source_info=source_info,
            reuse_features=reuse_features,
            allow_model_download=allow_model_download,
            skip_transcription=skip_transcription,
        )
        save_analysis_title(db_path, analysis_id, analysis_title)
    analysis = load_analysis(db_path, analysis_id)
    reused = analysis.get("cache", {}).get("reused_stages", [])
    if is_transcription_skipped(analysis.get("transcription")):
        st.session_state["analysis_notice"] = (
            "Speech recognition was skipped. This run used audio"
            + (" and chat" if analysis.get("chat", {}).get("path") else "")
            + " signals only."
        )
    else:
        st.session_state["analysis_notice"] = ("Reused cached " + ", ".join(reused) + ".") if reused else "Fresh source features generated."
    status.update(label="Analysis complete", state="complete", expanded=False)
    return analysis_id


def _run_queued_analysis(db_path: Path) -> None:
    queued = dict(st.session_state.get(_QUEUED_ANALYSIS_KEY) or {})
    if not queued:
        st.session_state.pop(_ANALYSIS_RUNNING_KEY, None)
        return

    try:
        st.session_state.analysis_id = _run_analysis_ui(db_path=db_path, **queued)
    except ModelDecisionRequired as exc:
        _queue_model_decision(exc, **queued)
    except Exception as exc:
        st.session_state["analysis_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _clear_queued_analysis_state()
    st.rerun()


def _queue_model_decision(exc: ModelDecisionRequired, **analysis_args) -> None:
    st.session_state[_PENDING_MODEL_ANALYSIS_KEY] = {
        **analysis_args,
        "message": str(exc),
    }


def _resume_pending_model_analysis(
    db_path: Path,
    *,
    allow_model_download: bool = False,
    skip_transcription: bool = False,
) -> None:
    del db_path
    pending = dict(st.session_state.get(_PENDING_MODEL_ANALYSIS_KEY) or {})
    if not pending:
        return
    pending.pop("message", None)
    _clear_pending_analysis_state()
    _queue_analysis(
        allow_model_download=allow_model_download,
        skip_transcription=skip_transcription,
        **pending,
    )
    st.rerun()


def _render_model_decision(db_path: Path) -> bool:
    pending = st.session_state.get(_PENDING_MODEL_ANALYSIS_KEY)
    if not pending:
        return False

    settings = load_app_settings(db_path)
    with st.container(border=True):
        st.subheader("Speech-recognition model required")
        st.write(pending.get("message") or f"The model {settings.whisper_model!r} is not installed.")
        st.caption(
            "Your VOD stays local. Downloading only retrieves the speech-recognition model from Hugging Face. "
            f"Downloaded models normally use `{huggingface_cache_directory()}`."
        )
        st.caption(
            "You can choose a complete local CTranslate2 Whisper model, or continue without speech recognition. "
            "Continuing remembers that model downloads are disabled and renormalizes scoring across the signals that remain available."
        )
        download, local, no_speech = st.columns(3)
        if download.button("Download model", type="primary", width="stretch"):
            set_model_download_consent("allow", db_path)
            _resume_pending_model_analysis(db_path, allow_model_download=True)
        if local.button("Choose local model", width="stretch"):
            try:
                selected = choose_folder("Choose a CTranslate2 Whisper model folder", str(models_root()))
                if selected:
                    validated = validate_local_model_directory(selected)
                    current = load_model_access(db_path)
                    save_model_access(
                        ModelAccessPreferences(current.download_consent, str(validated)),
                        db_path,
                    )
                    _resume_pending_model_analysis(db_path)
            except Exception as exc:
                st.exception(exc)
        if no_speech.button("Continue without speech", width="stretch"):
            set_model_download_consent("deny", db_path)
            _resume_pending_model_analysis(db_path, skip_transcription=True)
        if st.button("Cancel analysis", width="stretch"):
            _clear_pending_analysis_state()
            st.rerun()
    return True


def _render_source_sidebar(db_path: Path) -> tuple[str, str, str, str, str]:
    st.header("🎬 Source")
    st.caption("Choose local files directly. The VOD is read in place and never uploaded.")
    video_path = path_picker("VOD", "video_path_input", placeholder=r"D:\VODs\stream.mp4", file_filter=_VIDEO_FILTER)
    chat_path = path_picker("Chat file (optional)", "chat_path_input", placeholder="TwitchDownloader JSON / JSONL / CSV", file_filter=_CHAT_FILTER)
    content_label = persistent_text_input(
        "Content / Game",
        "content_label_input",
        placeholder="Just Chatting / Overwatch 2 / ...",
        help="Stored with every candidate for future preference learning.",
    )
    analysis_title = persistent_text_input(
        "Analysis title (optional)",
        "analysis_title_input",
        placeholder="Boss fight test / chat experiment / ...",
        help="Optional note for this run. The weighting profile is shown separately as the analysis name.",
    )
    work_dir = path_picker("Work folder", "work_dir_input", default=default_work_dir(), folder=True)

    settings = load_app_settings(db_path)
    effective = normalize_weights(settings.weights)
    st.caption(
        f"Settings: **{detect_weight_preset(settings.weights)}** · "
        f"audio {effective['audio']:.0%} / transcript {effective['transcript']:.0%} / chat {effective['chat']:.0%}"
    )

    dialog_error = st.session_state.pop("native_dialog_error", None)
    if dialog_error:
        st.error(dialog_error)
    return video_path, chat_path, content_label, analysis_title, work_dir


def _render_analysis_controls(
    db_path: Path,
    video_path: str,
    chat_path: str,
    content_label: str,
    analysis_title: str,
    work_dir: str,
) -> None:
    if _render_model_decision(db_path):
        return

    if st.button("⛏️ Analyze VOD", type="primary", width="stretch"):
        source = None
        try:
            source, prior_runs = find_source_runs(db_path, video_path)
            if prior_runs:
                st.session_state[_PENDING_RERUN_KEY] = {
                    "source": source,
                    "runs": prior_runs,
                    "video_path": str(Path(video_path).expanduser().resolve()),
                }
                st.rerun()
            _queue_analysis(
                video_path=video_path,
                chat_path=chat_path,
                content_label=content_label,
                analysis_title=analysis_title,
                work_dir=work_dir,
                source_info=source,
                reuse_features=True,
            )
            st.rerun()
        except Exception as exc:
            st.exception(exc)

    pending = st.session_state.get(_PENDING_RERUN_KEY)
    if not pending:
        return
    runs = pending.get("runs", [])
    latest = runs[0] if runs else None
    st.warning(f"This VOD already has {len(runs)} analysis run(s). Load the latest one or create a new run.")
    if latest:
        latest_identity = load_analysis_identity(db_path, latest["id"])
        latest_title = latest_identity.get("analysis_title", "")
        title_text = f" · {latest_title}" if latest_title else ""
        st.caption(
            f"Latest: {latest_identity['analysis_name']}{title_text} · run {latest['run_number']} · "
            f"{latest['candidates']} candidates · {latest['kept']} kept / "
            f"{latest['rejected']} rejected / {latest['unreviewed']} unreviewed"
        )
    force_fresh = st.checkbox("Force full reprocess", value=False, help="Normally compatible audio, Whisper transcript, and chat features are reused.", key="force_fresh_rerun")
    r1, r2 = st.columns(2)
    if latest and r1.button("Load latest", width="stretch"):
        st.session_state.analysis_id = latest["id"]
        st.session_state.pop(_PENDING_RERUN_KEY, None)
        st.rerun()
    if r2.button("Analyze again", type="primary", width="stretch"):
        _queue_analysis(
            video_path=video_path,
            chat_path=chat_path,
            content_label=content_label,
            analysis_title=analysis_title,
            work_dir=work_dir,
            source_info=pending.get("source"),
            reuse_features=not force_fresh,
        )
        st.session_state.pop(_PENDING_RERUN_KEY, None)
        st.rerun()


def _render_history_sidebar(db_path: Path) -> None:
    st.divider()
    st.subheader("🗃️ Analysis history")
    history = list_analyses(db_path, limit=50)
    if history:
        identities = load_analysis_identities(db_path, [row["id"] for row in history])
        labels = [_history_label(row, identities.get(row["id"], {})) for row in history]
        ids = [row["id"] for row in history]
        current_id = st.session_state.get("analysis_id")
        default_index = ids.index(current_id) if current_id in ids else 0
        selected = st.selectbox("Recent analyses", labels, index=default_index)
        selected_id = ids[labels.index(selected)]
        if st.button("Load selected analysis", width="stretch"):
            st.session_state.analysis_id = selected_id
            st.rerun()
    else:
        st.caption("No SQLite analyses yet.")

    with st.expander("Import v0.1 analysis.json"):
        legacy_path = path_picker("Legacy analysis.json", "legacy_analysis_input", placeholder=r"D:\HighlightMiner\highlightminer_work\stream\analysis.json", file_filter=_JSON_FILTER)
        if st.button("Import into database", disabled=not legacy_path, width="stretch"):
            try:
                st.session_state.analysis_id = import_legacy_analysis(legacy_path, db_path)
                st.session_state["analysis_notice"] = "Legacy analysis imported into SQLite."
                st.rerun()
            except Exception as exc:
                st.exception(exc)

    with st.expander("🧠 Learning data"):
        stats = learning_summary(db_path)
        st.caption(f"{stats['kept']} keep · {stats['rejected']} reject · {stats['unreviewed']} unreviewed · {stats['exported']} exported")
        st.caption("Unreviewed stays unlabeled; it is not silently treated as a reject.")


def _render_review(db_path: Path) -> None:
    analysis_id = st.session_state.get("analysis_id")
    if not analysis_id:
        st.info("Analyze a VOD, choose an item from **Analysis history**, or import a v0.1 `analysis.json`.")
        return
    try:
        analysis = load_analysis(db_path, analysis_id)
    except KeyError:
        st.session_state.pop("analysis_id", None)
        st.warning("That analysis no longer exists in the database.")
        return

    identity = load_analysis_identity(db_path, analysis_id)
    candidates = analysis.get("candidates", [])
    review = load_review(db_path, analysis_id, analysis)
    content_label = normalize_content_label(analysis.get("content_label"))
    transcription = analysis.get("transcription", {})
    transcription_skipped = is_transcription_skipped(transcription)
    st.subheader("📊 Analysis overview")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Candidates", len(candidates))
    c2.metric("Kept", sum(x.get("status") == "keep" for x in review["items"].values()))
    c3.metric("Rejected", sum(x.get("status") == "reject" for x in review["items"].values()))
    c4.metric("Unreviewed", sum(x.get("status") == "unreviewed" for x in review["items"].values()))
    c5.metric("Speech recognition", "Off" if transcription_skipped else (transcription.get("language") or "On"))
    reused = analysis.get("cache", {}).get("reused_stages", [])
    cache_text = f" · reused: {', '.join(reused)}" if reused else ""
    title_text = f" · Title: **{identity['analysis_title']}**" if identity.get("analysis_title") else ""
    st.caption(
        f"Analysis: **{identity['analysis_name']}**{title_text} · Content / Game: **{content_label}** · "
        f"source run **{analysis.get('run_number', 1)}** · Analysis ID: `{analysis_id[:12]}`{cache_text}"
    )
    if transcription_skipped:
        st.info("Speech recognition was disabled for this run. Candidate scoring was renormalized across audio and available chat signals.")
    if not candidates:
        st.warning("No candidates cleared the current threshold. Adjust Settings and analyze again.")
        return

    st.subheader("⛏️ Ranked candidates")
    st.dataframe(_candidate_rows(analysis, review), width="stretch", hide_index=True)
    labels = [f"{c['id']} · {c['score'] * 10:.1f}/10 · {format_time(c['peak_time'])} · {c['reason']}" for c in candidates]
    selected_label = st.selectbox("Review candidate", labels)
    candidate = candidates[labels.index(selected_label)]
    item = review["items"][candidate["id"]]

    st.subheader(f"🎞️ {candidate['id']} — {candidate['reason']}")
    left, right = st.columns(2)
    with left:
        start = st.number_input("Clip start (seconds)", min_value=0.0, max_value=float(analysis["duration"]), value=float(item["start"]), step=1.0, key=f"start_{analysis_id}_{candidate['id']}")
    with right:
        end = st.number_input("Clip end (seconds)", min_value=0.1, max_value=float(analysis["duration"]), value=float(item["end"]), step=1.0, key=f"end_{analysis_id}_{candidate['id']}")
    preview_end = max(float(end), float(start) + 0.1)
    preview_dir = Path(analysis["work_dir"]) / ".previews" / analysis_id
    try:
        source_video = validate_local_video(analysis["video_path"])
        with st.spinner("Preparing lightweight preview…"):
            preview_path = create_preview_clip(source_video, preview_dir, candidate["id"], float(start), preview_end)
        st.video(str(preview_path), width=640)
        st.caption(f"Local preview only: {format_time(float(start))} → {format_time(preview_end)}. The full source VOD is never sent to the UI player.")
    except Exception as exc:
        st.error("Could not build the lightweight preview clip. The stored source path may have moved or failed validation.")
        st.exception(exc)

    title = st.text_input("Optional clip title", value=item.get("title", ""), key=f"title_{analysis_id}_{candidate['id']}")
    st.caption(f"Signals — audio {candidate['audio_score']:.2f} · transcript {candidate['transcript_score']:.2f} · chat {candidate['chat_score']:.2f}")
    if candidate.get("transcript"):
        with st.expander("Transcript around this moment", expanded=True):
            st.write(candidate["transcript"])

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("✅ Keep", width="stretch"):
        item.update(status="keep", start=start, end=preview_end, title=title); save_review(db_path, analysis_id, review); st.rerun()
    if b2.button("❌ Reject", width="stretch"):
        item.update(status="reject", start=start, end=preview_end, title=title); save_review(db_path, analysis_id, review); st.rerun()
    if b3.button("↩ Unreview", width="stretch"):
        item.update(status="unreviewed", start=start, end=preview_end, title=title); save_review(db_path, analysis_id, review); st.rerun()
    if b4.button("💾 Save timing", width="stretch"):
        item.update(start=start, end=preview_end, title=title); save_review(db_path, analysis_id, review); st.success("Saved")

    st.divider()
    st.subheader("📦 Export")
    export_dir = path_picker("Export folder", "export_dir_input", default=str(Path(analysis["work_dir"]) / "clips"), folder=True)
    st.caption(f"Kept clips from this analysis will export under **{content_label}**. Existing files are never overwritten.")
    kept = [(c, review["items"][c["id"]]) for c in candidates if review["items"][c["id"]].get("status") == "keep"]
    if st.button(f"Export {len(kept)} kept clip(s)", disabled=not kept, type="primary"):
        exported = []
        progress = st.progress(0.0)
        source_video = validate_local_video(analysis["video_path"])
        for n, (candidate, review_item) in enumerate(kept, start=1):
            out = export_clip(
                source_video,
                export_dir,
                candidate["id"],
                review_item["start"],
                review_item["end"],
                review_item.get("title") or None,
                category=candidate.get("content_label") or analysis.get("content_label"),
            )
            record_export(db_path, analysis_id, candidate["id"], out)
            exported.append(str(out))
            progress.progress(n / len(kept))
        st.success(f"Exported {len(exported)} clip(s) to {Path(exported[0]).parent.resolve()}")
        st.code("\n".join(exported))


def render_mine_page(db_path: Path) -> None:
    _run_queued_analysis(db_path)

    with st.sidebar:
        video_path, chat_path, content_label, analysis_title, work_dir = _render_source_sidebar(db_path)
        _render_analysis_controls(db_path, video_path, chat_path, content_label, analysis_title, work_dir)
        _render_history_sidebar(db_path)
        st.caption(f"Database: `{db_path}`")
        render_shutdown()

    error = st.session_state.pop("analysis_error", None)
    if error:
        st.error(f"Analysis stopped: {error}")
    notice = st.session_state.pop("analysis_notice", None)
    if notice:
        st.success(notice)
    _render_review(db_path)
