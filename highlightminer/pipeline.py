from __future__ import annotations

from pathlib import Path
from typing import Callable

from .audio import analyze_audio
from .chat import analyze_chat, load_chat
from .config import Settings
from .media import extract_analysis_audio, probe_media
from .scoring import find_candidates
from .transcribe import transcribe_audio
from .util import ensure_dir, save_json

Progress = Callable[[str, float], None]


def _noop(_: str, __: float) -> None:
    pass


def analyze_vod(
    video_path: str | Path,
    work_dir: str | Path,
    settings: Settings,
    chat_path: str | Path | None = None,
    progress: Progress | None = None,
) -> Path:
    progress = progress or _noop
    video = Path(video_path).expanduser().resolve()
    if not video.exists():
        raise FileNotFoundError(video)
    work = ensure_dir(work_dir)

    progress("Probing media", 0.03)
    media = probe_media(video)
    duration = float(media["duration"])

    wav = work / "analysis_audio.wav"
    if not wav.exists():
        progress("Extracting 16 kHz analysis audio", 0.10)
        extract_analysis_audio(video, wav)

    progress("Analyzing audio energy", 0.20)
    audio_features = analyze_audio(wav, settings.audio_window_sec, settings.audio_hop_sec)
    save_json(work / "audio_features.json", audio_features)

    transcript_path = work / "transcript.json"
    meta_path = work / "transcript_meta.json"
    if transcript_path.exists() and meta_path.exists():
        from .util import load_json
        transcript = load_json(transcript_path)
        transcript_meta = load_json(meta_path)
    else:
        progress("Transcribing with faster-whisper", 0.32)
        transcript, transcript_meta = transcribe_audio(wav, settings)
        save_json(transcript_path, transcript)
        save_json(meta_path, transcript_meta)

    chat_features = []
    chat_info = {"path": None, "messages": 0}
    if chat_path:
        progress("Parsing chat", 0.76)
        records = load_chat(chat_path)
        chat_features = analyze_chat(records, duration)
        save_json(work / "chat_features.json", chat_features)
        chat_info = {"path": str(Path(chat_path).expanduser().resolve()), "messages": len(records)}

    progress("Ranking candidate moments", 0.86)
    candidates = find_candidates(duration, audio_features, transcript, chat_features, settings)

    analysis = {
        "version": 1,
        "video_path": str(video),
        "duration": duration,
        "media": media,
        "transcription": transcript_meta,
        "chat": chat_info,
        "settings": settings.__dict__,
        "candidates": candidates,
    }
    out = work / "analysis.json"
    save_json(out, analysis)
    progress(f"Done — {len(candidates)} candidates", 1.0)
    return out
