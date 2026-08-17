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
from .runtime import app_root, bundled_path, is_frozen
from .security import validate_local_video
from .storage import (
    default_db_path,
    import_legacy_analysis,
    list_analyses,
    load_analysis,
    record_export,
)

_STREAMLIT_CHILD_ARG = "__streamlit_child__"


def _progress(message: str, value: float) -> None:
    print(f"[{value * 100:5.1f}%] {message}", flush=True)


def cmd_analyze(args: argparse.Namespace) -> int:
    settings = Settings.from_file(args.settings)
    analysis_id = analyze_vod(
        args.video,
        args.work_dir,
        settings,
        args.chat,
        _progress,
        content_label=args.content,
        db_path=args.db,
    )
    print(f"Analysis ID: {analysis_id}")
    print(f"Database: {Path(args.db).expanduser().resolve()}")
    return 0


def _streamlit_app_path() -> Path:
    """Return the raw app.py path Streamlit needs to execute."""
    if is_frozen():
        return bundled_path("highlightminer", "app.py")
    return Path(__file__).resolve().with_name("app.py")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _run_streamlit_child(app_path: str) -> int:
    """Run Streamlit inside a frozen child process."""
    path = Path(app_path).resolve()
    if not path.is_file():
        print(f"Bundled Streamlit app not found: {path}", file=sys.stderr, flush=True)
        return 2

    from streamlit import config as streamlit_config
    from streamlit.runtime.credentials import check_credentials
    from streamlit.web import bootstrap

    main_script_path = os.path.abspath(path)
    streamlit_config._main_script_path = main_script_path
    flag_options = {
        "global_developmentMode": False,
        "server_headless": _env_bool("STREAMLIT_SERVER_HEADLESS", False),
        "server_address": "127.0.0.1",
        "server_port": 8501,
        "server_showEmailPrompt": False,
        "browser_serverAddress": "localhost",
        "browser_serverPort": 8501,
        "browser_gatherUsageStats": False,
    }
    bootstrap.load_config_options(flag_options=flag_options)
    check_credentials()

    print(f"Starting embedded Streamlit server for {main_script_path}", flush=True)
    bootstrap.run(main_script_path, False, [], flag_options)
    return 0


def _stop_ui_process(process: subprocess.Popen) -> None:
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


def cmd_ui(_: argparse.Namespace | None = None) -> int:
    app = _streamlit_app_path()
    if not app.is_file():
        raise RuntimeError(f"Streamlit application file is missing: {app}")

    shutdown_file = Path(tempfile.gettempdir()) / f"highlightminer-shutdown-{os.getpid()}.flag"
    shutdown_file.unlink(missing_ok=True)
    env = os.environ.copy()
    env["HIGHLIGHTMINER_SHUTDOWN_FILE"] = str(shutdown_file)

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    command = [sys.executable, _STREAMLIT_CHILD_ARG, str(app)] if is_frozen() else [
        sys.executable, "-m", "streamlit", "run", str(app)
    ]
    process = subprocess.Popen(command, env=env, creationflags=creationflags, cwd=str(app_root()))

    shutdown_requested = False
    try:
        while process.poll() is None:
            if shutdown_file.exists():
                shutdown_requested = True
                print("Shutdown requested from HighlightMiner UI...", flush=True)
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


def cmd_history(args: argparse.Namespace) -> int:
    rows = list_analyses(args.db, args.limit)
    if not rows:
        print("No analyses in the database.")
        return 0
    for row in rows:
        print(
            f"{row['id']}  {row['created_at']}  {row['content_label']}  "
            f"{row['video_name']}  candidates={row['candidates']} "
            f"kept={row['kept']} rejected={row['rejected']}"
        )
    return 0


def cmd_import_legacy(args: argparse.Namespace) -> int:
    analysis_id = import_legacy_analysis(args.analysis_json, args.db)
    print(f"Imported analysis ID: {analysis_id}")
    print(f"Database: {Path(args.db).expanduser().resolve()}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    analysis = load_analysis(args.db, args.analysis_id)
    review = load_review(args.db, args.analysis_id, analysis)
    out_dir = args.output or str(Path(analysis["work_dir"]) / "clips")
    source_video = validate_local_video(analysis["video_path"])

    chosen = []
    for c in analysis.get("candidates", []):
        r = review["items"][c["id"]]
        if args.all or r.get("status") == "keep":
            chosen.append((c, r))
    if not chosen:
        print("No clips selected. Mark clips Keep in the UI or pass --all.")
        return 2

    for c, r in chosen:
        category = c.get("content_label") or analysis.get("content_label")
        out = export_clip(
            source_video,
            out_dir,
            c["id"],
            r["start"],
            r["end"],
            r.get("title") or None,
            category=category,
        )
        record_export(args.db, args.analysis_id, c["id"], out)
        print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    program_name = "HighlightMiner.exe" if is_frozen() else "highlightminer"
    p = argparse.ArgumentParser(prog=program_name)
    sub = p.add_subparsers(dest="command", required=True)
    default_db = str(default_db_path())

    doctor = sub.add_parser("doctor", help="Check FFmpeg, faster-whisper, CUDA, and NVENC")
    doctor.set_defaults(func=lambda a: run_doctor())

    analyze = sub.add_parser("analyze", help="Analyze a local VOD and store it in SQLite")
    analyze.add_argument("video")
    analyze.add_argument("--chat", default=None, help="Optional chat JSON/JSONL/CSV")
    analyze.add_argument("--content", default=None, help="Content/game label")
    analyze.add_argument("--work-dir", default=str(app_root() / "highlightminer_work"))
    analyze.add_argument("--settings", default=str(app_root() / "settings.json"))
    analyze.add_argument("--db", default=default_db, help="SQLite database path")
    analyze.set_defaults(func=cmd_analyze)

    ui = sub.add_parser("ui", help="Launch the local review UI")
    ui.set_defaults(func=cmd_ui)

    history = sub.add_parser("history", help="List analyses stored in SQLite")
    history.add_argument("--db", default=default_db)
    history.add_argument("--limit", type=int, default=50)
    history.set_defaults(func=cmd_history)

    legacy = sub.add_parser("import-legacy", help="Import a v0.1 analysis.json into SQLite")
    legacy.add_argument("analysis_json")
    legacy.add_argument("--db", default=default_db)
    legacy.set_defaults(func=cmd_import_legacy)

    export = sub.add_parser("export", help="Export kept candidates from a database analysis")
    export.add_argument("analysis_id")
    export.add_argument("--db", default=default_db)
    export.add_argument("--output", default=None)
    export.add_argument("--all", action="store_true", help="Export every ranked candidate")
    export.set_defaults(func=cmd_export)
    return p


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == _STREAMLIT_CHILD_ARG:
        if len(sys.argv) != 3:
            raise SystemExit(2)
        raise SystemExit(_run_streamlit_child(sys.argv[2]))

    if is_frozen() and len(sys.argv) == 1:
        raise SystemExit(cmd_ui())

    args = build_parser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
