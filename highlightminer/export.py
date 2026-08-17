from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .categorization import content_folder_name
from .media import has_encoder, require_executable, require_ffmpeg
from .util import ensure_dir


def safe_name(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return text[:80] or "highlight"


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
        # The review UI must never push a multi-hour source VOD into Streamlit.
        # Render only the requested candidate window at a browser-friendly size.
        common += [
            "-vf",
            "scale='min(1280,iw)':-2,fps=30",
        ]

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
                    "-c:v",
                    "h264_nvenc",
                    "-preset",
                    "p4",
                    "-b:v",
                    "3M",
                    "-maxrate",
                    "4M",
                    "-bufsize",
                    "8M",
                ]
                audio_bitrate = "128k"
            else:
                video_args = [
                    "-c:v",
                    "h264_nvenc",
                    "-preset",
                    "p5",
                    "-cq",
                    "19",
                ]
                audio_bitrate = "192k"

            subprocess.run(finish(video_args, audio_bitrate), check=True)
            return
        except subprocess.CalledProcessError:
            # FFmpeg can advertise NVENC even when no usable NVIDIA device/driver exists.
            out.unlink(missing_ok=True)

    if preview:
        video_args = [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
        ]
        audio_bitrate = "128k"
    else:
        video_args = [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
        ]
        audio_bitrate = "192k"

    subprocess.run(finish(video_args, audio_bitrate), check=True)


def create_preview_clip(
    video_path: str | Path,
    output_dir: str | Path,
    clip_id: str,
    start: float,
    end: float,
) -> Path:
    """Create a small cached H.264 preview for the review UI.

    Streamlit should only receive this short file, never the original multi-hour VOD.
    The cache key includes the candidate timing so repeated UI reruns do not re-encode
    the same preview. Older previews for the same candidate are removed when timing
    changes.
    """
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
    require_ffmpeg()
    ffmpeg = require_executable("ffmpeg")
    src = Path(video_path).expanduser().resolve()
    base_dir = ensure_dir(output_dir)
    out_dir = ensure_dir(base_dir / content_folder_name(category))
    duration = max(0.1, float(end) - float(start))
    stem = safe_name(f"{clip_id}_{title}" if title else clip_id)
    out = out_dir / f"{stem}.mp4"

    _run_h264_encode(ffmpeg, src, out, float(start), duration, preview=False)
    return out
