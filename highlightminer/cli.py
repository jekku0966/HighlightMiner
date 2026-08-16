from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import Settings
from .doctor import run_doctor
from .export import export_clip
from .pipeline import analyze_vod
from .review import load_review
from .util import load_json


def _progress(message: str, value: float) -> None:
    print(f"[{value * 100:5.1f}%] {message}", flush=True)


def cmd_analyze(args: argparse.Namespace) -> int:
    settings = Settings.from_file(args.settings)
    out = analyze_vod(args.video, args.work_dir, settings, args.chat, _progress)
    print(out)
    return 0


def _stop_ui_process(process: subprocess.Popen) -> None:
    """Ask the Streamlit child to stop, then fall back to termination if needed."""
    if process.poll() is not None:
        return

    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        process.terminate()
        process.wait(timeout=3)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        process.kill()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        pass


def cmd_ui(_: argparse.Namespace) -> int:
    app = Path(__file__).resolve().with_name("app.py")
    shutdown_file = Path(tempfile.gettempdir()) / f"highlightminer-shutdown-{os.getpid()}.flag"
    shutdown_file.unlink(missing_ok=True)

    env = os.environ.copy()
    env["HIGHLIGHTMINER_SHUTDOWN_FILE"] = str(shutdown_file)

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(app)],
        env=env,
        creationflags=creationflags,
    )

    shutdown_requested = False
    try:
        while process.poll() is None:
            if shutdown_file.exists():
                shutdown_requested = True
                print("Shutdown requested from HighlightMiner UI...", flush=True)
                # Give Streamlit a moment to send the button response to the browser.
                time.sleep(0.75)
                _stop_ui_process(process)
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopping HighlightMiner UI...", flush=True)
        _stop_ui_process(process)
    finally:
        shutdown_file.unlink(missing_ok=True)

    if process.poll() is None:
        _stop_ui_process(process)

    return_code = process.wait()
    if shutdown_requested:
        print("HighlightMiner UI stopped.", flush=True)
        return 0
    return return_code


def cmd_export(args: argparse.Namespace) -> int:
    analysis_path = Path(args.analysis).expanduser().resolve()
    analysis = load_json(analysis_path)
    review = load_review(analysis_path.with_name("review.json"), analysis)
    out_dir = args.output or str(analysis_path.parent / "clips")

    chosen = []
    for c in analysis.get("candidates", []):
        r = review["items"][c["id"]]
        if args.all or r.get("status") == "keep":
            chosen.append((c, r))
    if not chosen:
        print("No clips selected. Mark clips Keep in the UI or pass --all.")
        return 2

    for c, r in chosen:
        out = export_clip(analysis["video_path"], out_dir, c["id"], r["start"], r["end"], r.get("title") or None)
        print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="highlightminer")
    sub = p.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check FFmpeg, faster-whisper, CUDA, and NVENC")
    doctor.set_defaults(func=lambda a: run_doctor())

    analyze = sub.add_parser("analyze", help="Analyze a local VOD")
    analyze.add_argument("video")
    analyze.add_argument("--chat", default=None, help="Optional chat JSON/JSONL/CSV")
    analyze.add_argument("--work-dir", default="./highlightminer_work")
    analyze.add_argument("--settings", default=str(Path(__file__).resolve().parent.parent / "settings.json"))
    analyze.set_defaults(func=cmd_analyze)

    ui = sub.add_parser("ui", help="Launch the local review UI")
    ui.set_defaults(func=cmd_ui)

    export = sub.add_parser("export", help="Export kept candidates from an analysis")
    export.add_argument("analysis")
    export.add_argument("--output", default=None)
    export.add_argument("--all", action="store_true", help="Export every ranked candidate")
    export.set_defaults(func=cmd_export)
    return p


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
