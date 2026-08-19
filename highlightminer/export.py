from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from .categorization import content_folder_name
from .diagnostics import ffmpeg_failure, log_detailed, log_event
from .media import has_encoder, require_executable, require_ffmpeg
from .util import ensure_dir


def safe_name(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return text[:80] or "highlight"


def _non_overwriting_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not find a free export filename.")


def _run_encode(command: list[str], *, encoder: str) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            shell=False,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        ffmpeg_failure("ffmpeg", exc)
        raise
    log_detailed("encoder.complete", encoder=encoder, exit_code=0)


def _run_h264_encode(
    ffmpeg: str,
    src: Path,
    out: Path,
    start: float,
    duration: float,
    *,
    preview: bool = False,
) -> None:
    common = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{float(start):.3f}",
        "-i",
        str(src),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
    ]

    if preview:
        common += ["-vf", "scale='min(1280,iw)':-2,fps=30"]

    def finish(video_args: list[str], audio_bitrate: str) -> list[str]:
        return [
            *common,
            *video_args,
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            str(out),
        ]

    if has_encoder("h264_nvenc"):
        try:
            if preview:
                video_args = [
                    "-c:v", "h264_nvenc", "-preset", "p4",
                    "-b:v", "3M", "-maxrate", "4M", "-bufsize", "8M",
                ]
                audio_bitrate = "128k"
            else:
                video_args = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19"]
                audio_bitrate = "192k"
            log_detailed("encoder.selection", encoder="h264_nvenc", preview=preview)
            _run_encode(finish(video_args, audio_bitrate), encoder="h264_nvenc")
            return
        except subprocess.CalledProcessError:
            log_event(
                "encoder.fallback",
                level=logging.WARNING,
                from_encoder="h264_nvenc",
                to_encoder="libx264",
                preview=preview,
            )
            out.unlink(missing_ok=True)

    if preview:
        video_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]
        audio_bitrate = "128k"
    else:
        video_args = ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
        audio_bitrate = "192k"

    log_detailed("encoder.selection", encoder="libx264", preview=preview)
    _run_encode(finish(video_args, audio_bitrate), encoder="libx264")


def create_preview_clip(
    video_path: str | Path,
    output_dir: str | Path,
    clip_id: str,
    start: float,
    end: float,
) -> Path:
    require_ffmpeg()
    ffmpeg = require_executable("ffmpeg")
    src = Path(video_path).expanduser().resolve()
    out_dir = ensure_dir(output_dir)

    start = max(0.0, float(start))
    end = max(start + 0.1, float(end))
    duration = end - start

    stem = safe_name(clip_id)
    signature = f"{start:.3f}_{end:.3f}".replace(".", "_")
    out = out_dir / f"{stem}_{signature}.mp4"

    if out.exists() and out.stat().st_size > 0:
        return out

    for old in out_dir.glob(f"{stem}_*.mp4"):
        old.unlink(missing_ok=True)

    _run_h264_encode(ffmpeg, src, out, start, duration, preview=True)
    return out


def export_clip(
    video_path: str | Path,
    output_dir: str | Path,
    clip_id: str,
    start: float,
    end: float,
    title: str | None = None,
    category: str | None = None,
) -> Path:
    """Export a clip without silently overwriting an older export."""
    require_ffmpeg()
    ffmpeg = require_executable("ffmpeg")
    src = Path(video_path).expanduser().resolve()
    base_dir = ensure_dir(output_dir)
    out_dir = ensure_dir(base_dir / content_folder_name(category))
    duration = max(0.1, float(end) - float(start))
    stem = safe_name(f"{clip_id}_{title}" if title else clip_id)
    out = _non_overwriting_path(out_dir / f"{stem}.mp4")

    _run_h264_encode(ffmpeg, src, out, float(start), duration, preview=False)
    log_event("export.complete", count=1)
    return out
