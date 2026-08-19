from __future__ import annotations

import atexit
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import __version__
from .runtime import app_root

STANDARD_MAX_BYTES = 2 * 1024 * 1024
DETAILED_MAX_BYTES = 10 * 1024 * 1024
STANDARD_RETAIN = 5
DETAILED_RETAIN = 2

_SESSION_ID = uuid.uuid4().hex[:12]
_STANDARD_LOGGER = logging.getLogger("highlightminer.standard")
_DETAILED_LOGGER = logging.getLogger("highlightminer.detailed")
_STANDARD_HANDLER: "_BoundedFileHandler | None" = None
_DETAILED_HANDLER: "_BoundedFileHandler | None" = None
_STARTUP_LOGGED = False
_SHUTDOWN_REGISTERED = False
_LOCK = threading.RLock()

_WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s\"'<>|]+")
_POSIX_PATH_RE = re.compile(r"(?<![:\w])/(?:[^\s\"'<>]+/)*[^\s\"'<>]*")
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|password|passwd|secret|token|credential)\b\s*[:=]\s*[^\s,;]+"
)
_FORBIDDEN_FIELD_PARTS = (
    "path",
    "transcript",
    "chat_message",
    "username",
    "user_name",
    "reaction_phrase",
    "sql",
    "credential",
    "environment",
    "media_content",
    "raw_data",
)


class _BoundedFileHandler(logging.FileHandler):
    """File handler that stops at a hard byte ceiling instead of rotating mid-session."""

    def __init__(self, filename: Path, max_bytes: int) -> None:
        self.max_bytes = int(max_bytes)
        self._full = False
        super().__init__(filename, mode="a", encoding="utf-8", delay=False)

    def emit(self, record: logging.LogRecord) -> None:
        if self._full:
            return
        try:
            message = self.format(record) + self.terminator
            payload = message.encode("utf-8", errors="replace")
            current = Path(self.baseFilename).stat().st_size if Path(self.baseFilename).exists() else 0
            if current + len(payload) > self.max_bytes:
                marker = '{"event":"log.limit_reached","note":"log file reached configured size limit"}\n'
                marker_bytes = marker.encode("utf-8")
                if current + len(marker_bytes) <= self.max_bytes and self.stream is not None:
                    self.stream.write(marker)
                    self.flush()
                self._full = True
                return
            if self.stream is None:
                self.stream = self._open()
            self.stream.write(message)
            self.flush()
        except Exception:
            self.handleError(record)


def session_id() -> str:
    return _SESSION_ID


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def log_folder() -> Path:
    preferred = app_root() / "logs"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path.home() / ".highlightminer" / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _prune(prefix: str, keep: int) -> None:
    files = sorted(
        (path for path in log_folder().glob(f"{prefix}*.log") if path.is_file()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def _redact_text(value: str) -> str:
    text = _SECRET_RE.sub(r"\1=<redacted>", str(value))
    text = _WINDOWS_PATH_RE.sub("<path>", text)
    text = _POSIX_PATH_RE.sub("<path>", text)
    return text


def _forbidden_field(key: str) -> bool:
    lowered = key.casefold()
    return any(part in lowered for part in _FORBIDDEN_FIELD_PARTS)


def _safe_value(value: Any, *, key: str = "") -> Any:
    if _forbidden_field(key):
        return "<redacted>"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {str(k): _safe_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item, key=key) for item in value]
    return _redact_text(type(value).__name__)


def _handler_for(kind: str, max_bytes: int) -> _BoundedFileHandler:
    filename = log_folder() / f"{kind}-{_timestamp()}-{_SESSION_ID}.log"
    handler = _BoundedFileHandler(filename, max_bytes=max_bytes)
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def configure_standard_logging() -> Path:
    global _STANDARD_HANDLER, _SHUTDOWN_REGISTERED
    with _LOCK:
        if _STANDARD_HANDLER is None:
            _STANDARD_LOGGER.setLevel(logging.INFO)
            _STANDARD_LOGGER.propagate = False
            _STANDARD_HANDLER = _handler_for("standard", STANDARD_MAX_BYTES)
            _STANDARD_LOGGER.handlers[:] = [_STANDARD_HANDLER]
            _prune("standard-", STANDARD_RETAIN)
        if not _SHUTDOWN_REGISTERED:
            atexit.register(shutdown_logging)
            _SHUTDOWN_REGISTERED = True
        return Path(_STANDARD_HANDLER.baseFilename)


def log_startup(*, entrypoint: str) -> None:
    global _STARTUP_LOGGED
    configure_standard_logging()
    with _LOCK:
        if _STARTUP_LOGGED:
            return
        _STARTUP_LOGGED = True
    log_event("app.startup", entrypoint=entrypoint)


def shutdown_logging() -> None:
    global _STANDARD_HANDLER, _DETAILED_HANDLER
    with _LOCK:
        if _STANDARD_HANDLER is not None:
            log_event("app.shutdown")
        for logger, handler in ((_DETAILED_LOGGER, _DETAILED_HANDLER), (_STANDARD_LOGGER, _STANDARD_HANDLER)):
            if handler is not None:
                try:
                    handler.flush()
                    handler.close()
                finally:
                    logger.handlers[:] = []
        _DETAILED_HANDLER = None
        _STANDARD_HANDLER = None


def _payload(level: str, event: str, fields: dict[str, Any]) -> str:
    data = {
        "timestamp": _iso_now(),
        "level": level,
        "event": str(event),
        "app_version": __version__,
        "session_id": _SESSION_ID,
    }
    data.update({str(key): _safe_value(value, key=str(key)) for key, value in fields.items()})
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _emit(logger: logging.Logger, level: int, event: str, fields: dict[str, Any]) -> None:
    if logger.handlers:
        logger.log(level, _payload(logging.getLevelName(level), event, fields))


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    configure_standard_logging()
    _emit(_STANDARD_LOGGER, level, event, fields)
    _emit(_DETAILED_LOGGER, level, event, fields)


def log_warning(event: str, **fields: Any) -> None:
    log_event(event, level=logging.WARNING, **fields)


def log_exception(event: str, exc: BaseException, **fields: Any) -> None:
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    safe_fields = dict(fields)
    safe_fields.update(error_type=type(exc).__name__, traceback=_redact_text(formatted))
    log_event(event, level=logging.ERROR, **safe_fields)


def detailed_active() -> bool:
    return _DETAILED_HANDLER is not None


def start_detailed_run(run_id: str | None = None) -> Path:
    global _DETAILED_HANDLER
    configure_standard_logging()
    with _LOCK:
        if _DETAILED_HANDLER is not None:
            return Path(_DETAILED_HANDLER.baseFilename)
        suffix = (run_id or uuid.uuid4().hex[:8]).strip()[:24]
        filename = log_folder() / f"detailed-{_timestamp()}-{_SESSION_ID}-{suffix}.log"
        _DETAILED_LOGGER.setLevel(logging.INFO)
        _DETAILED_LOGGER.propagate = False
        _DETAILED_HANDLER = _BoundedFileHandler(filename, max_bytes=DETAILED_MAX_BYTES)
        _DETAILED_HANDLER.setFormatter(logging.Formatter("%(message)s"))
        _DETAILED_LOGGER.handlers[:] = [_DETAILED_HANDLER]
        _prune("detailed-", DETAILED_RETAIN)
    log_event("diagnostics.detailed_start")
    return filename


def stop_detailed_run() -> None:
    global _DETAILED_HANDLER
    with _LOCK:
        handler = _DETAILED_HANDLER
        if handler is None:
            return
        _emit(_DETAILED_LOGGER, logging.INFO, "diagnostics.detailed_end", {})
        handler.flush()
        handler.close()
        _DETAILED_LOGGER.handlers[:] = []
        _DETAILED_HANDLER = None


def log_detailed(event: str, **fields: Any) -> None:
    _emit(_DETAILED_LOGGER, logging.INFO, event, fields)


@contextmanager
def diagnostic_stage(name: str, **fields: Any) -> Iterator[None]:
    started = time.perf_counter()
    log_event("stage.start", stage=name, **fields)
    try:
        yield
    except Exception as exc:
        duration = max(0.0, time.perf_counter() - started)
        log_exception("stage.error", exc, stage=name, duration_seconds=duration)
        raise
    else:
        duration = max(0.0, time.perf_counter() - started)
        log_event("stage.complete", stage=name, duration_seconds=duration)


def safe_model_name(name: str, source: str) -> str:
    return "local-model" if str(source).casefold() == "local" else _redact_text(name)


def redacted_settings(settings: Any) -> dict[str, Any]:
    weights = dict(getattr(settings, "weights", {}) or {})
    return {
        "model": str(getattr(settings, "whisper_model", "")),
        "device": str(getattr(settings, "device", "")),
        "compute_type": str(getattr(settings, "compute_type", "")),
        "language_mode": "fixed" if getattr(settings, "language", None) else "auto",
        "beam_size": int(getattr(settings, "beam_size", 0)),
        "vad_filter": bool(getattr(settings, "vad_filter", False)),
        "audio_window_sec": float(getattr(settings, "audio_window_sec", 0.0)),
        "audio_hop_sec": float(getattr(settings, "audio_hop_sec", 0.0)),
        "pre_roll_sec": float(getattr(settings, "pre_roll_sec", 0.0)),
        "post_roll_sec": float(getattr(settings, "post_roll_sec", 0.0)),
        "merge_gap_sec": float(getattr(settings, "merge_gap_sec", 0.0)),
        "max_candidate_sec": float(getattr(settings, "max_candidate_sec", 0.0)),
        "min_candidate_score": float(getattr(settings, "min_candidate_score", 0.0)),
        "max_candidates": int(getattr(settings, "max_candidates", 0)),
        "weights": {key: float(weights.get(key, 0.0)) for key in ("audio", "transcript", "chat")},
        "reaction_phrases": "<redacted>",
    }


def media_summary(media: dict[str, Any]) -> dict[str, Any]:
    streams = []
    for stream in list(media.get("streams") or []):
        streams.append(
            {
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "frame_rate": stream.get("r_frame_rate"),
            }
        )
    return {"duration_seconds": float(media.get("duration") or 0.0), "streams": streams}


def signal_statistics(rows: list[dict[str, Any]], *, score_key: str = "score") -> dict[str, Any]:
    scores: list[float] = []
    for row in rows:
        try:
            scores.append(float(row.get(score_key, 0.0)))
        except (TypeError, ValueError):
            continue
    if not scores:
        return {"count": len(rows), "score_min": None, "score_max": None, "score_mean": None}
    return {
        "count": len(rows),
        "score_min": min(scores),
        "score_max": max(scores),
        "score_mean": sum(scores) / len(scores),
    }


def ffmpeg_failure(tool: str, exc: subprocess.CalledProcessError) -> None:
    stderr = _redact_text(str(exc.stderr or ""))
    log_event(
        "ffmpeg.failure",
        level=logging.ERROR,
        tool=str(tool),
        exit_code=int(exc.returncode),
        stderr=stderr,
    )


def open_log_folder() -> Path:
    folder = log_folder()
    if os.name == "nt":
        os.startfile(folder)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return folder


def diagnostic_summary(*, detailed_armed: bool) -> str:
    standard = sorted(log_folder().glob("standard-*.log"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    detailed = sorted(log_folder().glob("detailed-*.log"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    lines = [
        f"HighlightMiner {__version__}",
        f"Session: {_SESSION_ID}",
        "Standard logging: enabled",
        f"Detailed diagnostics for next run: {'armed' if detailed_armed else 'off'}",
        f"Latest Standard log: {standard[0].name if standard else 'none'}",
        f"Latest Detailed log: {detailed[0].name if detailed else 'none'}",
        "Logs are local only and are never uploaded automatically.",
    ]
    return "\n".join(lines)


def delete_logs() -> int:
    global _STANDARD_HANDLER, _DETAILED_HANDLER, _STARTUP_LOGGED
    with _LOCK:
        for logger, handler in ((_DETAILED_LOGGER, _DETAILED_HANDLER), (_STANDARD_LOGGER, _STANDARD_HANDLER)):
            if handler is not None:
                handler.flush()
                handler.close()
                logger.handlers[:] = []
        _DETAILED_HANDLER = None
        _STANDARD_HANDLER = None
        removed = 0
        for path in list(log_folder().glob("standard-*.log")) + list(log_folder().glob("detailed-*.log")):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        _STARTUP_LOGGED = False
    configure_standard_logging()
    log_startup(entrypoint="settings-after-delete")
    return removed
