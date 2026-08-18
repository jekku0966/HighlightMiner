from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from .audio import analyze_audio
from .categorization import normalize_content_label
from .chat import analyze_chat, load_chat
from .config import Settings
from .identity import describe_source, full_file_sha256, stable_signature
from .learning import rerank_candidates
from .learning_store import prepare_preference_model
from .media import extract_analysis_audio, probe_media
from .model_access import (
    ModelAccessPreferences,
    PreparedModelReference,
    load_model_access,
    model_signature_payload,
    resolve_model_reference,
)
from .scoring import find_candidates
from .security import validate_chat_file, validate_local_video
from .settings_presets import detect_weight_preset
from .storage import (
    ALGORITHM_VERSION,
    FEATURE_SCHEMA_VERSION,
    load_reusable_features,
    register_source,
    save_analysis,
)
from .transcribe import score_text, transcribe_audio
from .transcription_status import (
    SKIP_REASON_MODEL_DOWNLOADS_DISABLED,
    SKIP_REASON_USER_REQUESTED,
    TRANSCRIPTION_AVAILABLE,
    is_transcription_skipped,
    skipped_transcription_metadata,
)
from .util import ensure_dir

Progress = Callable[[str, float], None]


def _noop(_: str, __: float) -> None:
    pass


def _stage_signatures(
    settings: Settings,
    chat_path: str | Path | None,
    model_access: ModelAccessPreferences,
) -> dict[str, str]:
    audio = stable_signature(
        "highlightminer-audio-features-v1",
        {
            "window": settings.audio_window_sec,
            "hop": settings.audio_hop_sec,
            "analysis_audio": "pcm_s16le-16khz-mono",
        },
    )
    transcript = stable_signature(
        "highlightminer-whisper-transcript-v1",
        {
            "model": model_signature_payload(settings, model_access),
            "device": settings.device,
            "compute_type": settings.compute_type,
            "language": settings.language,
            "beam_size": settings.beam_size,
            "vad_filter": settings.vad_filter,
        },
    )
    if chat_path:
        validated_chat = validate_chat_file(chat_path)
        chat = stable_signature(
            "highlightminer-chat-features-v1",
            {"sha256": full_file_sha256(validated_chat)},
        )
    else:
        chat = stable_signature("highlightminer-chat-features-v1", {"chat": None})
    return {"audio": audio, "transcript": transcript, "chat": chat}


def _rescore_transcript(rows: list[dict], settings: Settings) -> list[dict]:
    rescored: list[dict] = []
    for row in rows:
        score, reasons = score_text(str(row.get("text", "")), settings.reaction_phrases)
        updated = dict(row)
        updated["score"] = round(score, 4)
        updated["reasons"] = reasons
        rescored.append(updated)
    return rescored


def analyze_vod(
    video_path: str | Path,
    work_dir: str | Path,
    settings: Settings,
    chat_path: str | Path | None = None,
    progress: Progress | None = None,
    content_label: str | None = None,
    db_path: str | Path | None = None,
    *,
    source_info: dict | None = None,
    reuse_features: bool = True,
    allow_model_download: bool = False,
    skip_transcription: bool = False,
) -> str:
    """Analyze a VOD and persist a new analysis run in SQLite.

    Compatible feature stages are reused from prior runs. A fresh Whisper pass
    is resolved only when actually needed. If model downloads were explicitly
    denied and no local/cached model exists, mining continues with audio plus
    optional chat. Preference learning remains a conservative fail-open reranker.
    """
    progress = progress or _noop
    video = validate_local_video(video_path)
    work = ensure_dir(work_dir)
    normalized_content_label = normalize_content_label(content_label)
    mining_profile = detect_weight_preset(settings.weights)
    model_access = load_model_access(db_path)

    progress("Identifying source VOD", 0.01)
    actual_source = describe_source(video)
    if source_info and source_info.get("fingerprint") == actual_source["fingerprint"]:
        actual_source["fingerprint"] = str(source_info["fingerprint"])
    source = register_source(db_path, actual_source)
    signatures = _stage_signatures(settings, chat_path, model_access)
    cached = (
        load_reusable_features(
            db_path,
            source["id"],
            audio_signature=signatures["audio"],
            transcript_signature=signatures["transcript"],
            chat_signature=signatures["chat"],
        )
        if reuse_features
        else {"audio": None, "transcript": None, "transcription": None, "chat": None, "chat_info": None, "from": {}}
    )

    progress("Probing media", 0.03)
    media = probe_media(video)
    duration = float(media["duration"])
    if duration <= 0:
        raise ValueError("The VOD duration reported by ffprobe is invalid.")

    audio_features = cached.get("audio")
    transcript = cached.get("transcript")
    transcript_meta = cached.get("transcription")
    chat_features = cached.get("chat")
    chat_info = cached.get("chat_info")
    cache_from = dict(cached.get("from") or {})

    need_audio = audio_features is None
    need_transcript = transcript is None
    prepared_model: PreparedModelReference | None = None

    if skip_transcription:
        transcript = []
        transcript_meta = skipped_transcription_metadata(
            settings.whisper_model,
            SKIP_REASON_USER_REQUESTED,
        )
        cache_from.pop("transcript", None)
        need_transcript = False
    elif need_transcript:
        # Resolver semantics are intentional: None means the user explicitly
        # denied downloads; an undecided policy raises ModelDecisionRequired so
        # an interactive caller can ask before any network access is permitted.
        prepared_model = resolve_model_reference(
            settings,
            model_access,
            allow_download_override=allow_model_download,
        )
        if prepared_model is None:
            transcript = []
            transcript_meta = skipped_transcription_metadata(
                settings.whisper_model,
                SKIP_REASON_MODEL_DOWNLOADS_DISABLED,
            )
            need_transcript = False

    transcription_skipped = is_transcription_skipped(transcript_meta)
    skip_reason = str((transcript_meta or {}).get("reason") or "") if transcription_skipped else None
    need_wav = need_audio or need_transcript
    wav: Path | None = None

    try:
        if need_wav:
            temp_handle = tempfile.NamedTemporaryFile(
                prefix="highlightminer-",
                suffix=".wav",
                dir=work,
                delete=False,
            )
            wav = Path(temp_handle.name)
            temp_handle.close()
            progress("Extracting 16 kHz analysis audio", 0.10)
            extract_analysis_audio(video, wav)
        elif transcription_skipped:
            progress("Speech recognition disabled; using available signals", 0.16)
        else:
            progress("Reusing cached analysis audio features + transcript", 0.16)

        if need_audio:
            progress("Analyzing audio energy", 0.20)
            assert wav is not None
            audio_features = analyze_audio(wav, settings.audio_window_sec, settings.audio_hop_sec)
        else:
            progress("Reusing cached audio features", 0.24)

        if need_transcript:
            progress("Transcribing with faster-whisper", 0.32)
            assert wav is not None
            assert prepared_model is not None
            transcript, transcript_meta = transcribe_audio(
                wav,
                settings,
                model_access=model_access,
                prepared_model=prepared_model,
            )
        elif transcription_skipped:
            progress("Skipping speech recognition", 0.60)
        else:
            progress("Reusing cached Whisper transcript", 0.60)

        transcript = _rescore_transcript(list(transcript or []), settings)
        transcript_meta = dict(transcript_meta or {})
        if not transcription_skipped:
            transcript_meta.setdefault("status", TRANSCRIPTION_AVAILABLE)
            transcript_meta["reaction_scoring"] = "current-settings"

        if chat_path:
            validated_chat = validate_chat_file(chat_path)
            if chat_features is None:
                progress("Parsing chat", 0.76)
                records = load_chat(validated_chat)
                chat_features = analyze_chat(records, duration)
                chat_info = {"path": str(validated_chat), "messages": len(records)}
            else:
                progress("Reusing cached chat features", 0.78)
                chat_info = dict(chat_info or {})
                chat_info["path"] = str(validated_chat)
        else:
            chat_features = []
            chat_info = {"path": None, "messages": 0}

        progress("Ranking candidate moments", 0.86)
        candidates = find_candidates(
            duration,
            list(audio_features or []),
            transcript,
            list(chat_features or []),
            settings,
            transcript_available=not transcription_skipped,
        )
        for candidate in candidates:
            candidate["content_label"] = normalized_content_label
            features = dict(candidate.get("features") or {})
            features["context"] = {
                "content_label": normalized_content_label,
                "mining_profile": mining_profile,
                "has_transcript": not transcription_skipped,
            }
            candidate["features"] = features

        learning_info: dict = {
            "active": False,
            "state": "warming_up",
            "reason": "Preference learner has not been prepared yet.",
            "content_label": normalized_content_label,
            "mining_profile": mining_profile,
        }
        try:
            progress("Applying personal reranker", 0.92)
            prepared_learning = prepare_preference_model(db_path)
            candidates, learning_info = rerank_candidates(
                candidates,
                prepared_learning.model,
                model_id=prepared_learning.model_id,
                content_label=normalized_content_label,
                mining_profile=mining_profile,
            )
            learning_info.update(
                {
                    "state": prepared_learning.training.state,
                    "reason": prepared_learning.training.reason,
                    "reused_existing_model": prepared_learning.reused_existing_model,
                }
            )
        except Exception as exc:
            learning_info = {
                "active": False,
                "state": "error",
                "reason": f"Learner disabled for this run: {type(exc).__name__}: {exc}",
                "content_label": normalized_content_label,
                "mining_profile": mining_profile,
            }

        cache_info = {
            "reused": cache_from,
            "reused_stages": sorted(cache_from),
            "reuse_enabled": bool(reuse_features),
            "mining_profile": mining_profile,
            "learning": learning_info,
            "transcription_skipped": transcription_skipped,
            "transcription_skip_reason": skip_reason,
        }
        analysis = {
            "version": 2,
            "video_path": str(video),
            "content_label": normalized_content_label,
            "duration": duration,
            "media": media,
            "transcription": transcript_meta,
            "chat": chat_info,
            "settings": settings.__dict__,
            "algorithm_version": ALGORITHM_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "candidates": candidates,
        }
        progress("Saving analysis database", 0.96)
        save_signatures: dict[str, str | None] = dict(signatures)
        if transcription_skipped:
            save_signatures["transcript"] = None
        analysis_id = save_analysis(
            db_path,
            analysis,
            transcript,
            list(audio_features or []),
            list(chat_features or []),
            work_dir=work,
            source=source,
            signatures=save_signatures,
            cache_info=cache_info,
        )
        reused = ", ".join(sorted(cache_from))
        suffix = f" · reused {reused}" if reused else ""
        if transcription_skipped:
            suffix += " · no transcript"
        learning_suffix = " · personalized" if learning_info.get("active") else ""
        progress(f"Done — {len(candidates)} candidates{suffix}{learning_suffix}", 1.0)
        return analysis_id
    finally:
        if wav is not None:
            try:
                wav.unlink(missing_ok=True)
            except OSError:
                pass
