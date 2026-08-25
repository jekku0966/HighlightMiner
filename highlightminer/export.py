from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .categorization import content_folder_name
from .diagnostics import ffmpeg_failure, log_detailed, log_event, log_exception
from .media import has_encoder, require_executable, require_ffmpeg
from .util import ensure_dir

_PREVIEW_CACHE_KEEP = 4
_PREVIEW_CLEANUP_RETRIES = 3
_PREVIEW_CLEANUP_DELAY_SEC = 0.05
_PREVIEW_GENERATION_LOCK = threading.RLock()


@dataclass(frozen=True)
class PreviewClipResult:
    path: Path
    cleanup_failures: int = 0


class PreviewFileLockError(PermissionError):
    """A temporary preview could not be removed or replaced due to file access."""


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


def _retry_unlink(path: Path) -> bool:
    """Best-effort deletion for preview files that may still be held by Windows."""
    for attempt in range(_PREVIEW_CLEANUP_RETRIES):
        try:
            path.unlink(missing_ok=True)
            return True
        except FileNotFoundError:
            return True
        except (PermissionError, OSError):
            if attempt + 1 < _PREVIEW_CLEANUP_RETRIES:
                time.sleep(_PREVIEW_CLEANUP_DELAY_SEC)
    return False


def _prune_preview_files(out_dir: Path, stem: str, *, keep_path: Path) -> int:
    """Prune old previews and return the number that remained after retries."""
    previews: list[Path] = []
    for path in out_dir.glob(f"{stem}_*.mp4"):
        try:
            if path.is_file():
                previews.append(path)
        except OSError:
            continue

    def modified(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    previews.sort(key=modified, reverse=True)
    protected = {keep_path}
    cleanup_failures = 0
    for path in previews:
        if path == keep_path:
            continue
        if len(protected) < _PREVIEW_CACHE_KEEP:
            protected.add(path)
            continue
        if not _retry_unlink(path):
            cleanup_failures += 1
    if cleanup_failures:
        log_event(
            "preview.cleanup_failed",
            level=logging.WARNING,
            failed_files=cleanup_failures,
        )
    return cleanup_failures


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
    try:
        _run_encode(finish(video_args, audio_bitrate), encoder="libx264")
    except subprocess.CalledProcessError as exc:
        log_exception("encoder.error", exc, encoder="libx264", preview=preview)
        raise


def create_preview_clip(
    video_path: str | Path,
    output_dir: str | Path,
    clip_id: str,
    start: float,
    end: float,
) -> PreviewClipResult:
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
    partial = out.with_name(f".{out.stem}.partial{out.suffix}")

    # Streamlit/browser video playback can keep an earlier preview open on
    # Windows. Never delete the currently displayed predecessor before the
    # replacement has been encoded successfully.
    with _PREVIEW_GENERATION_LOCK:
        if out.exists() and out.stat().st_size > 0:
            cleanup_failures = _prune_preview_files(out_dir, stem, keep_path=out)
            return PreviewClipResult(out, cleanup_failures)

        if not _retry_unlink(partial):
            raise PreviewFileLockError("Could not remove an incomplete preview from an earlier attempt.")
        try:
            _run_h264_encode(ffmpeg, src, partial, start, duration, preview=True)
            try:
                partial.replace(out)
            except PermissionError as exc:
                raise PreviewFileLockError("Could not replace the temporary preview file.") from exc
        except Exception:
            _retry_unlink(partial)
            raise
        cleanup_failures = _prune_preview_files(out_dir, stem, keep_path=out)
        return PreviewClipResult(out, cleanup_failures)


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
