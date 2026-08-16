from __future__ import annotations

import argparse
import subprocess
import sys
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


def cmd_ui(_: argparse.Namespace) -> int:
    app = Path(__file__).resolve().with_name("app.py")
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])


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
