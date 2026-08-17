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
from .util import load_json

_STREAMLIT_CHILD_ARG = "__streamlit_child__"


def _progress(message: str, value: float) -> None:
    print(f"[{value * 100:5.1f}%] {message}", flush=True)


def cmd_analyze(args: argparse.Namespace) -> int:
    settings = Settings.from_file(args.settings)
    out = analyze_vod(
        args.video,
        args.work_dir,
        settings,
        args.chat,
        _progress,
        content_label=args.content,
    )
    print(out)
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
    """Run Streamlit inside a frozen child process.

    A PyInstaller executable is not a Python interpreter, so a frozen
    HighlightMiner cannot launch ``sys.executable -m streamlit``. The parent
    instead spawns HighlightMiner.exe again with this private mode. The child
    reproduces Streamlit's CLI startup sequence directly inside the embedded
    runtime and then enters Streamlit's blocking server bootstrap.
    """
    path = Path(app_path).resolve()
    if not path.is_file():
        print(f"Bundled Streamlit app not found: {path}", file=sys.stderr, flush=True)
        return 2

    from streamlit import config as streamlit_config
    from streamlit.runtime.credentials import check_credentials
    from streamlit.web import bootstrap

    main_script_path = os.path.abspath(path)
    streamlit_config._main_script_path = main_script_path

    # Streamlit's normal Click CLI converts environment variables into these
    # flag options before calling bootstrap. A frozen HighlightMiner bypasses
    # Click, so pass the options explicitly instead. The packaged UI is bound
    # only to loopback: it is a local desktop-style application, not a LAN web
    # service. Development mode is explicitly disabled for the frozen app. This
    # also avoids the first-run email prompt and disables Streamlit's own
    # usage-statistics telemetry.
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


def cmd_ui(_: argparse.Namespace | None = None) -> int:
    app = _streamlit_app_path()
    if not app.is_file():
        raise RuntimeError(f"Streamlit application file is missing: {app}")

    shutdown_file = Path(tempfile.gettempdir()) / f"highlightminer-shutdown-{os.getpid()}.flag"
    shutdown_file.unlink(missing_ok=True)

    env = os.environ.copy()
    env["HIGHLIGHTMINER_SHUTDOWN_FILE"] = str(shutdown_file)

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    if is_frozen():
        command = [sys.executable, _STREAMLIT_CHILD_ARG, str(app)]
    else:
        command = [sys.executable, "-m", "streamlit", "run", str(app)]

    process = subprocess.Popen(
        command,
        env=env,
        creationflags=creationflags,
        cwd=str(app_root()),
        shell=False,
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
        category = c.get("content_label") or analysis.get("content_label")
        out = export_clip(
            analysis["video_path"],
            out_dir,
            c["id"],
            r["start"],
            r["end"],
            r.get("title") or None,
            category=category,
        )
        print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    program_name = "HighlightMiner.exe" if is_frozen() else "highlightminer"
    p = argparse.ArgumentParser(prog=program_name)
    sub = p.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check FFmpeg, faster-whisper, CUDA, and NVENC")
    doctor.set_defaults(func=lambda a: run_doctor())

    analyze = sub.add_parser("analyze", help="Analyze a local VOD")
    analyze.add_argument("video")
    analyze.add_argument("--chat", default=None, help="Optional chat JSON/JSONL/CSV")
    analyze.add_argument("--content", default=None, help="Content/game label used for organization and future preference learning")
    analyze.add_argument("--work-dir", default=str(app_root() / "highlightminer_work"))
    analyze.add_argument("--settings", default=str(app_root() / "settings.json"))
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
    # Private child mode used only by a frozen HighlightMiner.exe.
    if len(sys.argv) >= 2 and sys.argv[1] == _STREAMLIT_CHILD_ARG:
        if len(sys.argv) != 3:
            raise SystemExit(2)
        raise SystemExit(_run_streamlit_child(sys.argv[2]))

    # Double-clicking the packaged executable launches the UI. Source-mode CLI
    # behavior remains unchanged and still requires an explicit subcommand.
    if is_frozen() and len(sys.argv) == 1:
        raise SystemExit(cmd_ui())

    args = build_parser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
