from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

# FFmpeg/ffprobe are invoked through their documented CLI. No FFmpeg code is bundled.
# See ATTRIBUTIONS.md for provenance/licensing notes.


def _run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=capture,
        check=True,
        encoding="utf-8",
        errors="replace",
    )


def require_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(
            "Missing executable(s): " + ", ".join(missing) + ". Install FFmpeg and add it to PATH."
        )


def probe_media(path: str | Path) -> dict:
    require_ffmpeg()
    p = str(Path(path).expanduser().resolve())
    result = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json", p,
    ])
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    if duration <= 0:
        raise RuntimeError(f"Could not determine duration for {p}")
    return {"duration": duration, "streams": data.get("streams", [])}


def extract_analysis_audio(video_path: str | Path, wav_path: str | Path) -> Path:
    require_ffmpeg()
    src = str(Path(video_path).expanduser().resolve())
    dst = Path(wav_path).expanduser().resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst),
    ])
    return dst


@lru_cache(maxsize=32)
def has_encoder(name: str) -> bool:
    require_ffmpeg()
    try:
        result = _run(["ffmpeg", "-hide_banner", "-encoders"])
    except subprocess.CalledProcessError:
        return False
    return name in result.stdout
