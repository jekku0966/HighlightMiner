from __future__ import annotations

from pathlib import Path

import streamlit as st

from highlightminer.config import Settings
from highlightminer.export import create_preview_clip, export_clip
from highlightminer.pipeline import analyze_vod
from highlightminer.review import load_review, save_review
from highlightminer.util import format_time, load_json

# UI uses Streamlit public APIs documented at docs.streamlit.io.
# No Streamlit source code is vendored; see ATTRIBUTIONS.md.


def _default_settings_path() -> str:
    root = Path(__file__).resolve().parent.parent
    p = root / "settings.json"
    return str(p) if p.exists() else "settings.json"


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


def main() -> None:
    st.set_page_config(page_title="HighlightMiner", page_icon="⛏️", layout="wide")
    st.title("⛏️ HighlightMiner")
    st.caption("Local VOD scrubber: audio + Whisper transcript + optional chat → ranked moments → review → export.")

    with st.sidebar:
        st.header("Source")
        video_path = st.text_input("VOD path", value=st.session_state.get("video_path", ""), placeholder=r"D:\VODs\stream.mp4")
        chat_path = st.text_input("Chat file (optional)", value=st.session_state.get("chat_path", ""), placeholder="TwitchDownloader JSON / JSONL / CSV")
        work_dir = st.text_input("Work folder", value=st.session_state.get("work_dir", "./highlightminer_work"))
        settings_path = st.text_input("Settings", value=st.session_state.get("settings_path", _default_settings_path()))

        if st.button("Analyze VOD", type="primary", width="stretch"):
            st.session_state.video_path = video_path
            st.session_state.chat_path = chat_path
            st.session_state.work_dir = work_dir
            st.session_state.settings_path = settings_path
            try:
                settings = Settings.from_file(settings_path if settings_path else None)
                status = st.status("Analyzing…", expanded=True)
                bar = st.progress(0.0)
                label = st.empty()

                def progress(message: str, value: float) -> None:
                    label.write(message)
                    bar.progress(min(1.0, max(0.0, value)))

                analysis_path = analyze_vod(video_path, work_dir, settings, chat_path or None, progress)
                st.session_state.analysis_path = str(analysis_path)
                status.update(label="Analysis complete", state="complete", expanded=False)
            except Exception as exc:
                st.exception(exc)

        st.divider()
        analysis_path_text = st.text_input(
            "Existing analysis.json",
            value=st.session_state.get("analysis_path", str(Path(work_dir) / "analysis.json")),
        )
        if st.button("Load analysis", width="stretch"):
            st.session_state.analysis_path = analysis_path_text
            st.rerun()

    analysis_path = Path(st.session_state.get("analysis_path", analysis_path_text))
    if not analysis_path.exists():
        st.info("Enter a local VOD path in the sidebar and run **Analyze VOD**.")
        return

    analysis = load_json(analysis_path)
    candidates = analysis.get("candidates", [])
    review_path = analysis_path.with_name("review.json")
    review = load_review(review_path, analysis)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Candidates", len(candidates))
    c2.metric("Kept", sum(x.get("status") == "keep" for x in review["items"].values()))
    c3.metric("Rejected", sum(x.get("status") == "reject" for x in review["items"].values()))
    lang = analysis.get("transcription", {}).get("language") or "?"
    c4.metric("Whisper language", lang)

    if not candidates:
        st.warning("No candidates cleared the current threshold. Lower `min_candidate_score` in settings.json and analyze again.")
        return

    st.subheader("Ranked candidates")
    st.dataframe(_candidate_rows(analysis, review), width="stretch", hide_index=True)

    labels = [f"{c['id']} · {c['score'] * 10:.1f}/10 · {format_time(c['peak_time'])} · {c['reason']}" for c in candidates]
    selected_label = st.selectbox("Review candidate", labels)
    idx = labels.index(selected_label)
    cand = candidates[idx]
    item = review["items"][cand["id"]]

    st.subheader(f"{cand['id']} — {cand['reason']}")

    left, right = st.columns(2)
    with left:
        start = st.number_input(
            "Clip start (seconds)", min_value=0.0, max_value=float(analysis["duration"]),
            value=float(item["start"]), step=1.0, key=f"start_{cand['id']}"
        )
    with right:
        end = st.number_input(
            "Clip end (seconds)", min_value=0.1, max_value=float(analysis["duration"]),
            value=float(item["end"]), step=1.0, key=f"end_{cand['id']}"
        )

    preview_end = max(float(end), float(start) + 0.1)
    preview_dir = analysis_path.parent / ".previews"
    try:
        with st.spinner("Preparing lightweight preview…"):
            preview_path = create_preview_clip(
                analysis["video_path"],
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
        st.error("Could not build the lightweight preview clip.")
        st.exception(exc)

    title = st.text_input("Optional clip title", value=item.get("title", ""), key=f"title_{cand['id']}")

    st.caption(
        f"Signals — audio {cand['audio_score']:.2f} · transcript {cand['transcript_score']:.2f} · chat {cand['chat_score']:.2f}"
    )
    if cand.get("transcript"):
        with st.expander("Transcript around this moment", expanded=True):
            st.write(cand["transcript"])

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("✅ Keep", width="stretch"):
        item.update(status="keep", start=start, end=preview_end, title=title)
        save_review(review_path, review)
        st.rerun()
    if b2.button("❌ Reject", width="stretch"):
        item.update(status="reject", start=start, end=preview_end, title=title)
        save_review(review_path, review)
        st.rerun()
    if b3.button("↩ Unreview", width="stretch"):
        item.update(status="unreviewed", start=start, end=preview_end, title=title)
        save_review(review_path, review)
        st.rerun()
    if b4.button("💾 Save timing", width="stretch"):
        item.update(start=start, end=preview_end, title=title)
        save_review(review_path, review)
        st.success("Saved")

    st.divider()
    export_dir = st.text_input("Export folder", value=str(analysis_path.parent / "clips"))
    kept = [(c, review["items"][c["id"]]) for c in candidates if review["items"][c["id"]].get("status") == "keep"]
    if st.button(f"Export {len(kept)} kept clip(s)", disabled=not kept, type="primary"):
        exported = []
        progress = st.progress(0.0)
        for n, (c, r) in enumerate(kept, start=1):
            out = export_clip(
                analysis["video_path"], export_dir, c["id"], r["start"], r["end"], r.get("title") or None
            )
            exported.append(str(out))
            progress.progress(n / len(kept))
        st.success(f"Exported {len(exported)} clip(s) to {Path(export_dir).resolve()}")
        st.code("\n".join(exported))


if __name__ == "__main__":
    main()
