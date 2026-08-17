from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

import streamlit as st

from highlightminer.categorization import normalize_content_label
from highlightminer.config import Settings
from highlightminer.export import create_preview_clip, export_clip
from highlightminer.pipeline import analyze_vod
from highlightminer.review import load_review, save_review
from highlightminer.runtime import app_root
from highlightminer.security import validate_local_video
from highlightminer.storage import (
    default_db_path,
    import_legacy_analysis,
    list_analyses,
    load_analysis,
    record_export,
)
from highlightminer.util import format_time

# UI uses Streamlit public APIs documented at docs.streamlit.io.
# No Streamlit source code is vendored; see ATTRIBUTIONS.md.

_VIDEO_FILTER = "Video files|*.mp4;*.mkv;*.mov;*.webm;*.avi;*.m4v;*.ts|All files|*.*"
_CHAT_FILTER = "Chat files|*.json;*.jsonl;*.ndjson;*.csv|All files|*.*"
_JSON_FILTER = "JSON files|*.json|All files|*.*"


def _default_settings_path() -> str:
    p = app_root() / "settings.json"
    return str(p) if p.exists() else "settings.json"


def _default_work_dir() -> str:
    return str(app_root() / "highlightminer_work")


def _dialog_initial_directory(value: str | None) -> str:
    if value:
        candidate = Path(value).expanduser()
        if candidate.is_file():
            candidate = candidate.parent
        elif not candidate.is_dir():
            candidate = candidate.parent
        if candidate.is_dir():
            return str(candidate.resolve())
    return str(Path.home())


def _ps_literal(value: str) -> str:
    return value.replace("'", "''")


def _run_windows_dialog(script: str) -> str | None:
    """Run a native Windows picker in a separate STA PowerShell process."""
    if os.name != "nt":
        raise RuntimeError(
            "Native Browse buttons are currently available on Windows only. "
            "Enter the path manually on this platform."
        )

    wrapped = (
        "$ErrorActionPreference = 'Stop';"
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false);"
        + script
    )
    encoded = base64.b64encode(wrapped.encode("utf-16le")).decode("ascii")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-EncodedCommand", encoded],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
        check=False,
    )
    stdout = result.stdout.decode("utf-8-sig", errors="replace").strip()
    stderr = result.stderr.decode("utf-8-sig", errors="replace").strip()
    if result.returncode != 0:
        raise RuntimeError(stderr or f"Native file dialog failed with exit code {result.returncode}.")
    return stdout or None


def _choose_file(title: str, file_filter: str, initial: str | None = None) -> str | None:
    initial_dir = _dialog_initial_directory(initial)
    script = f"""
Add-Type -AssemblyName System.Windows.Forms;
$dialog = New-Object System.Windows.Forms.OpenFileDialog;
$dialog.Title = '{_ps_literal(title)}';
$dialog.Filter = '{_ps_literal(file_filter)}';
$dialog.InitialDirectory = '{_ps_literal(initial_dir)}';
$dialog.CheckFileExists = $true;
$dialog.Multiselect = $false;
$dialog.RestoreDirectory = $true;
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::Out.Write($dialog.FileName);
}}
$dialog.Dispose();
"""
    return _run_windows_dialog(script)


def _choose_folder(title: str, initial: str | None = None) -> str | None:
    initial_dir = _dialog_initial_directory(initial)
    script = f"""
Add-Type -AssemblyName System.Windows.Forms;
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;
$dialog.Description = '{_ps_literal(title)}';
$dialog.SelectedPath = '{_ps_literal(initial_dir)}';
$dialog.ShowNewFolderButton = $true;
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::Out.Write($dialog.SelectedPath);
}}
$dialog.Dispose();
"""
    return _run_windows_dialog(script)


def _browse_into_state(
    state_key: str,
    title: str,
    *,
    folder: bool = False,
    file_filter: str = "All files|*.*",
) -> None:
    try:
        current = st.session_state.get(state_key, "")
        selected = _choose_folder(title, current) if folder else _choose_file(title, file_filter, current)
        if selected:
            st.session_state[state_key] = selected
    except Exception as exc:
        st.session_state["native_dialog_error"] = str(exc)


def _path_picker(
    label: str,
    state_key: str,
    *,
    default: str = "",
    placeholder: str | None = None,
    folder: bool = False,
    file_filter: str = "All files|*.*",
) -> str:
    if state_key not in st.session_state:
        st.session_state[state_key] = default

    path_col, browse_col = st.columns([4, 1], vertical_alignment="bottom")
    with path_col:
        st.text_input(label, key=state_key, placeholder=placeholder)
    with browse_col:
        st.button(
            "Browse",
            key=f"browse_{state_key}",
            width="stretch",
            help=f"Choose {label.lower()} from this computer",
            on_click=_browse_into_state,
            args=(state_key, f"Choose {label}"),
            kwargs={"folder": folder, "file_filter": file_filter},
        )
    return str(st.session_state.get(state_key, ""))


def _candidate_rows(analysis: dict, review: dict) -> list[dict]:
    rows = []
    for c in analysis.get("candidates", []):
        r = review["items"].get(c["id"], {})
        rows.append({
            "#": c["rank"],
            "ID": c["id"],
            "Score": round(c["score"] * 10, 1),
            "Start": format_time(r.get("start", c["start"])),
            "End": format_time(r.get("end", c["end"])),
            "Why": c["reason"],
            "Status": r.get("status", "unreviewed"),
        })
    return rows


def _history_label(row: dict) -> str:
    created = str(row.get("created_at", "")).replace("T", " ").replace("+00:00", " UTC")
    return (
        f"{row['content_label']} · {row['video_name']} · {created} · "
        f"{row['candidates']} candidates · {row['kept']} kept"
    )


def main() -> None:
    st.set_page_config(page_title="HighlightMiner", page_icon="⛏️", layout="wide")
    db_path = default_db_path()

    with st.container(border=True):
        st.title("⛏️ HighlightMiner")
        st.caption(
            "Mine long VODs for the moments worth keeping — audio + Whisper + optional chat, "
            "ranked locally on your machine. v0.2 stores analysis history in SQLite."
        )

    with st.sidebar:
        st.header("🎬 Source")
        st.caption("Choose local files directly. The VOD is read in place and is never uploaded through the browser.")

        video_path = _path_picker(
            "VOD",
            "video_path_input",
            default=st.session_state.get("video_path", ""),
            placeholder=r"D:\VODs\stream.mp4",
            file_filter=_VIDEO_FILTER,
        )
        chat_path = _path_picker(
            "Chat file (optional)",
            "chat_path_input",
            default=st.session_state.get("chat_path", ""),
            placeholder="TwitchDownloader JSON / JSONL / CSV",
            file_filter=_CHAT_FILTER,
        )
        content_label = st.text_input(
            "Content / Game",
            key="content_label_input",
            placeholder="Just Chatting / Overwatch 2 / ...",
            help="One primary label for this VOD. It is stored with every candidate for future preference learning.",
        )
        work_dir = _path_picker(
            "Work folder",
            "work_dir_input",
            default=st.session_state.get("work_dir", _default_work_dir()),
            folder=True,
        )
        settings_path = _path_picker(
            "Settings",
            "settings_path_input",
            default=st.session_state.get("settings_path", _default_settings_path()),
            file_filter=_JSON_FILTER,
        )

        dialog_error = st.session_state.pop("native_dialog_error", None)
        if dialog_error:
            st.error(dialog_error)

        if st.button("⛏️ Analyze VOD", type="primary", width="stretch"):
            try:
                settings = Settings.from_file(settings_path if settings_path else None)
                status = st.status("Analyzing…", expanded=True)
                bar = st.progress(0.0)
                label = st.empty()

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
                )
                st.session_state.analysis_id = analysis_id
                status.update(label="Analysis complete", state="complete", expanded=False)
                st.rerun()
            except Exception as exc:
                st.exception(exc)

        st.divider()
        st.subheader("🗃️ Analysis history")
        history = list_analyses(db_path, limit=50)
        if history:
            labels = [_history_label(row) for row in history]
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
            legacy_path = _path_picker(
                "Legacy analysis.json",
                "legacy_analysis_input",
                placeholder=r"D:\HighlightMiner\highlightminer_work\stream\analysis.json",
                file_filter=_JSON_FILTER,
            )
            if st.button("Import into database", disabled=not legacy_path, width="stretch"):
                try:
                    imported_id = import_legacy_analysis(legacy_path, db_path)
                    st.session_state.analysis_id = imported_id
                    st.success("Legacy analysis imported.")
                    st.rerun()
                except Exception as exc:
                    st.exception(exc)

        st.caption(f"Database: `{db_path}`")

        shutdown_file = os.environ.get("HIGHLIGHTMINER_SHUTDOWN_FILE")
        if shutdown_file:
            st.divider()
            if st.button("🛑 Exit HighlightMiner", width="stretch"):
                try:
                    Path(shutdown_file).write_text("shutdown\n", encoding="utf-8")
                except OSError as exc:
                    st.error(f"Could not request shutdown: {exc}")
                else:
                    st.info("Shutting down HighlightMiner… You can close this browser tab.")
                    st.stop()

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

    candidates = analysis.get("candidates", [])
    review = load_review(db_path, analysis_id, analysis)
    content_label = normalize_content_label(analysis.get("content_label"))

    st.subheader("📊 Analysis overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Candidates", len(candidates))
    c2.metric("Kept", sum(x.get("status") == "keep" for x in review["items"].values()))
    c3.metric("Rejected", sum(x.get("status") == "reject" for x in review["items"].values()))
    lang = analysis.get("transcription", {}).get("language") or "?"
    c4.metric("Whisper language", lang)
    st.caption(f"Content / Game: **{content_label}** · Analysis ID: `{analysis_id[:12]}`")

    if not candidates:
        st.warning("No candidates cleared the current threshold. Adjust settings and analyze again.")
        return

    st.subheader("⛏️ Ranked candidates")
    st.dataframe(_candidate_rows(analysis, review), width="stretch", hide_index=True)

    labels = [f"{c['id']} · {c['score'] * 10:.1f}/10 · {format_time(c['peak_time'])} · {c['reason']}" for c in candidates]
    selected_label = st.selectbox("Review candidate", labels)
    idx = labels.index(selected_label)
    cand = candidates[idx]
    item = review["items"][cand["id"]]

    st.subheader(f"🎞️ {cand['id']} — {cand['reason']}")

    left, right = st.columns(2)
    with left:
        start = st.number_input(
            "Clip start (seconds)",
            min_value=0.0,
            max_value=float(analysis["duration"]),
            value=float(item["start"]),
            step=1.0,
            key=f"start_{analysis_id}_{cand['id']}",
        )
    with right:
        end = st.number_input(
            "Clip end (seconds)",
            min_value=0.1,
            max_value=float(analysis["duration"]),
            value=float(item["end"]),
            step=1.0,
            key=f"end_{analysis_id}_{cand['id']}",
        )

    preview_end = max(float(end), float(start) + 0.1)
    preview_dir = Path(analysis["work_dir"]) / ".previews" / analysis_id
    try:
        source_video = validate_local_video(analysis["video_path"])
        with st.spinner("Preparing lightweight preview…"):
            preview_path = create_preview_clip(
                source_video,
                preview_dir,
                cand["id"],
                float(start),
                preview_end,
            )
        st.video(str(preview_path), width=640)
        st.caption(
            f"Local preview only: {format_time(float(start))} → {format_time(preview_end)}. "
            "The full source VOD is never sent to the browser player."
        )
    except Exception as exc:
        st.error("Could not build the lightweight preview clip. The stored source path may have moved or failed validation.")
        st.exception(exc)

    title = st.text_input(
        "Optional clip title",
        value=item.get("title", ""),
        key=f"title_{analysis_id}_{cand['id']}",
    )

    st.caption(
        f"Signals — audio {cand['audio_score']:.2f} · transcript {cand['transcript_score']:.2f} · chat {cand['chat_score']:.2f}"
    )
    if cand.get("transcript"):
        with st.expander("Transcript around this moment", expanded=True):
            st.write(cand["transcript"])

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("✅ Keep", width="stretch"):
        item.update(status="keep", start=start, end=preview_end, title=title)
        save_review(db_path, analysis_id, review)
        st.rerun()
    if b2.button("❌ Reject", width="stretch"):
        item.update(status="reject", start=start, end=preview_end, title=title)
        save_review(db_path, analysis_id, review)
        st.rerun()
    if b3.button("↩ Unreview", width="stretch"):
        item.update(status="unreviewed", start=start, end=preview_end, title=title)
        save_review(db_path, analysis_id, review)
        st.rerun()
    if b4.button("💾 Save timing", width="stretch"):
        item.update(start=start, end=preview_end, title=title)
        save_review(db_path, analysis_id, review)
        st.success("Saved")

    st.divider()
    st.subheader("📦 Export")
    export_dir = _path_picker(
        "Export folder",
        "export_dir_input",
        default=str(Path(analysis["work_dir"]) / "clips"),
        folder=True,
    )
    st.caption(f"Kept clips from this analysis will export under **{content_label}**.")
    kept = [
        (c, review["items"][c["id"]])
        for c in candidates
        if review["items"][c["id"]].get("status") == "keep"
    ]
    if st.button(f"Export {len(kept)} kept clip(s)", disabled=not kept, type="primary"):
        exported = []
        progress = st.progress(0.0)
        source_video = validate_local_video(analysis["video_path"])
        for n, (c, r) in enumerate(kept, start=1):
            category = c.get("content_label") or analysis.get("content_label")
            out = export_clip(
                source_video,
                export_dir,
                c["id"],
                r["start"],
                r["end"],
                r.get("title") or None,
                category=category,
            )
            record_export(db_path, analysis_id, c["id"], out)
            exported.append(str(out))
            progress.progress(n / len(kept))
        destination = Path(exported[0]).parent.resolve()
        st.success(f"Exported {len(exported)} clip(s) to {destination}")
        st.code("\n".join(exported))


if __name__ == "__main__":
    main()
