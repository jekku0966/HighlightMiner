from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from .audio import analyze_audio
from .categorization import normalize_content_label
from .chat import analyze_chat, load_chat
from .config import Settings
from .media import extract_analysis_audio, probe_media
from .scoring import find_candidates
from .security import validate_local_video
from .storage import save_analysis
from .transcribe import transcribe_audio
from .util import ensure_dir

Progress = Callable[[str, float], None]


def _noop(_: str, __: float) -> None:
    pass


def analyze_vod(
    video_path: str | Path,
    work_dir: str | Path,
    settings: Settings,
    chat_path: str | Path | None = None,
    progress: Progress | None = None,
    content_label: str | None = None,
    db_path: str | Path | None = None,
) -> str:
    """Analyze a VOD and persist the result to the HighlightMiner database.

    v0.2 keeps durable state in SQLite. The extracted 16 kHz WAV is temporary:
    once audio features and the transcript have been committed, it is removed.
    """
    progress = progress or _noop
    video = validate_local_video(video_path)
    work = ensure_dir(work_dir)
    normalized_content_label = normalize_content_label(content_label)

    progress("Probing media", 0.03)
    media = probe_media(video)
    duration = float(media["duration"])
    if duration <= 0:
        raise ValueError("The VOD duration reported by ffprobe is invalid.")

    temp_handle = tempfile.NamedTemporaryFile(
        prefix="highlightminer-",
        suffix=".wav",
        dir=work,
        delete=False,
    )
    wav = Path(temp_handle.name)
    temp_handle.close()

    try:
        progress("Extracting 16 kHz analysis audio", 0.10)
        extract_analysis_audio(video, wav)

        progress("Analyzing audio energy", 0.20)
        audio_features = analyze_audio(wav, settings.audio_window_sec, settings.audio_hop_sec)

        progress("Transcribing with faster-whisper", 0.32)
        transcript, transcript_meta = transcribe_audio(wav, settings)

        chat_features: list[dict] = []
        chat_info = {"path": None, "messages": 0}
        if chat_path:
            progress("Parsing chat", 0.76)
            records = load_chat(chat_path)
            chat_features = analyze_chat(records, duration)
            chat_info = {
                "path": str(Path(chat_path).expanduser().resolve()),
                "messages": len(records),
            }

        progress("Ranking candidate moments", 0.86)
        candidates = find_candidates(duration, audio_features, transcript, chat_features, settings)
        for candidate in candidates:
            candidate["content_label"] = normalized_content_label

        analysis = {
            "version": 2,
            "video_path": str(video),
            "content_label": normalized_content_label,
            "duration": duration,
            "media": media,
            "transcription": transcript_meta,
            "chat": chat_info,
            "settings": settings.__dict__,
            "candidates": candidates,
        }
        progress("Saving analysis database", 0.96)
        analysis_id = save_analysis(
            db_path,
            analysis,
            transcript,
            audio_features,
            chat_features,
            work_dir=work,
        )
        progress(f"Done — {len(candidates)} candidates", 1.0)
        return analysis_id
    finally:
        try:
            wav.unlink(missing_ok=True)
        except OSError:
            # A failed cleanup must not destroy an otherwise successful analysis.
            pass
