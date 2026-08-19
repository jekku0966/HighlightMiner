from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .diagnostics import ffmpeg_failure, log_detailed
from .runtime import app_root

# FFmpeg/ffprobe are invoked through their documented CLI. No FFmpeg code is bundled.
# See ATTRIBUTIONS.md for provenance/licensing notes.


def find_executable(name: str) -> str | None:
    """Find an executable bundled locally with HighlightMiner or on system PATH."""
    root = app_root()
    filenames = [f"{name}.exe", name] if os.name == "nt" else [name]

    # Prefer a portable ./bin folder, then the repository/application root.
    for source, directory in (("portable-bin", root / "bin"), ("app-root", root)):
        for filename in filenames:
            candidate = directory / filename
            if candidate.is_file():
                log_detailed("ffmpeg.executable_resolution", tool=name, source=source)
                return str(candidate)

    # Fall back to the normal operating-system PATH lookup without logging PATH itself.
    resolved = shutil.which(name)
    if resolved:
        log_detailed("ffmpeg.executable_resolution", tool=name, source="system-path")
    return resolved


def require_executable(name: str) -> str:
    path = find_executable(name)
    if path is None:
        raise RuntimeError(
            f"Missing executable: {name}. Put it in HighlightMiner/bin, "
            "put it beside run.bat / HighlightMiner.exe, or add it to PATH."
        )
    return path


def _run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=capture,
            check=True,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        ffmpeg_failure(Path(cmd[0]).name, exc)
        raise
    log_detailed("ffmpeg.complete", tool=Path(cmd[0]).name, exit_code=int(result.returncode))
    return result


def require_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if find_executable(name) is None]
    if missing:
        raise RuntimeError(
            "Missing executable(s): "
            + ", ".join(missing)
            + ". Put them in HighlightMiner/bin, beside run.bat / HighlightMiner.exe, or add them to PATH."
        )


def probe_media(path: str | Path) -> dict:
    require_ffmpeg()
    ffprobe = require_executable("ffprobe")
    p = str(Path(path).expanduser().resolve())
    result = _run([
        ffprobe, "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json", p,
    ])
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    if duration <= 0:
        raise RuntimeError("Could not determine media duration.")
    return {"duration": duration, "streams": data.get("streams", [])}


def extract_analysis_audio(video_path: str | Path, wav_path: str | Path) -> Path:
    require_ffmpeg()
    ffmpeg = require_executable("ffmpeg")
    src = str(Path(video_path).expanduser().resolve())
    dst = Path(wav_path).expanduser().resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst),
    ])
    return dst


@lru_cache(maxsize=32)
def has_encoder(name: str) -> bool:
    require_ffmpeg()
    ffmpeg = require_executable("ffmpeg")
    try:
        result = _run([ffmpeg, "-hide_banner", "-encoders"])
    except subprocess.CalledProcessError:
        return False
    return name in result.stdout
