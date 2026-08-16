from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .media import has_encoder, require_ffmpeg
from .util import ensure_dir


def safe_name(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return text[:80] or "highlight"


def export_clip(
    video_path: str | Path,
    output_dir: str | Path,
    clip_id: str,
    start: float,
    end: float,
    title: str | None = None,
) -> Path:
    require_ffmpeg()
    src = Path(video_path).expanduser().resolve()
    out_dir = ensure_dir(output_dir)
    duration = max(0.1, float(end) - float(start))
    stem = safe_name(f"{clip_id}_{title}" if title else clip_id)
    out = out_dir / f"{stem}.mp4"

    def command(video_args: list[str]) -> list[str]:
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{float(start):.3f}", "-i", str(src), "-t", f"{duration:.3f}",
            "-map", "0:v:0?", "-map", "0:a:0?",
            *video_args,
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out),
        ]

    if has_encoder("h264_nvenc"):
        try:
            subprocess.run(command(["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19"]), check=True)
            return out
        except subprocess.CalledProcessError:
            # An FFmpeg build can advertise NVENC even when no usable NVIDIA device/driver is present.
            out.unlink(missing_ok=True)

    subprocess.run(command(["-c:v", "libx264", "-preset", "medium", "-crf", "18"]), check=True)
    return out
