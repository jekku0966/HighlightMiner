from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Callable

from .audio import analyze_audio
from .categorization import normalize_content_label
from .chat import analyze_chat, load_chat
from .config import Settings
from .diagnostic_preferences import (
    consume_detailed_diagnostics_next_run,
    detailed_diagnostics_next_run,
)
from .diagnostics import (
    diagnostic_stage,
    log_detailed,
    log_event,
    log_exception,
    media_summary,
    redacted_settings,
    safe_model_name,
    signal_statistics,
    start_detailed_run,
    stop_detailed_run,
)
from .identity import describe_source, full_file_sha256, stable_signature
from .learning import rerank_candidates
from .learning_store import prepare_preference_model
from .media import extract_analysis_audio, probe_media
from .model_access import (
    ModelAccessPreferences,
    ModelDecisionRequired,
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
from .util import clamp, ensure_dir

Progress = Callable[[str, float], None]

_TRANSCRIPTION_PROGRESS_START = 0.32
_TRANSCRIPTION_PROGRESS_END = 0.76


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
    # Reaction phrase scoring is deliberately excluded: cached transcript text
    # can be cheaply rescored without re-running Whisper.
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


def _elapsed_since(started_at: float) -> float:
    """Measure rounded elapsed seconds for persisted timing metadata."""
    return round(max(0.0, time.perf_counter() - started_at), 3)


def _map_transcription_progress(fraction: float) -> float:
    """Map Whisper's 0..1 progress into its reserved pipeline progress range."""
    bounded = clamp(float(fraction))
    span = _TRANSCRIPTION_PROGRESS_END - _TRANSCRIPTION_PROGRESS_START
    return _TRANSCRIPTION_PROGRESS_START + (span * bounded)


def _log_model_metadata(metadata: dict | None, settings: Settings) -> None:
    data = dict(metadata or {})
    source = str(data.get("model_source") or "configured")
    model_name = safe_model_name(str(data.get("model") or settings.whisper_model), source)
    log_event(
        "model.runtime",
        model_name=model_name,
        model_source=source,
        device=str(data.get("device") or settings.device),
        compute_type=str(data.get("compute_type") or settings.compute_type),
        fallback=bool(data.get("fallback_reason")),
    )


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
    pipeline_started_at = time.perf_counter()
    timings: dict[str, float] = {}
    wav: Path | None = None
    detailed_started = False

    log_event(
        "analysis.start",
        reuse_enabled=bool(reuse_features),
        chat_available=bool(chat_path),
        transcription_requested=not bool(skip_transcription),
    )

    try:
        detailed_requested = detailed_diagnostics_next_run(db_path)
        if detailed_requested:
            start_detailed_run()
            detailed_started = True
            log_detailed("settings.redacted", settings=redacted_settings(settings))

        video = validate_local_video(video_path)
        work = ensure_dir(work_dir)
        normalized_content_label = normalize_content_label(content_label)
        mining_profile = detect_weight_preset(settings.weights)
        model_access = load_model_access(db_path)
        log_detailed("database.operation", operation="load_model_access")

        source_started_at = time.perf_counter()
        progress("Identifying source VOD", 0.01)
        with diagnostic_stage("source_setup"):
            actual_source = describe_source(video)
            if source_info and source_info.get("fingerprint") == actual_source["fingerprint"]:
                actual_source["fingerprint"] = str(source_info["fingerprint"])
            log_detailed("database.operation", operation="register_source")
            source = register_source(db_path, actual_source)
            signatures = _stage_signatures(settings, chat_path, model_access)
            if reuse_features:
                log_detailed("database.operation", operation="load_reusable_features")
                cached = load_reusable_features(
                    db_path,
                    source["id"],
                    audio_signature=signatures["audio"],
                    transcript_signature=signatures["transcript"],
                    chat_signature=signatures["chat"],
                )
            else:
                cached = {
                    "audio": None,
                    "transcript": None,
                    "transcription": None,
                    "chat": None,
                    "chat_info": None,
                    "from": {},
                }
        timings["source_setup_seconds"] = _elapsed_since(source_started_at)

        probe_started_at = time.perf_counter()
        progress("Probing media", 0.03)
        with diagnostic_stage("media_probe"):
            media = probe_media(video)
        timings["media_probe_seconds"] = _elapsed_since(probe_started_at)
        duration = float(media["duration"])
        if duration <= 0:
            raise ValueError("The VOD duration reported by ffprobe is invalid.")
        log_detailed("media.info", media=media_summary(media))

        audio_features = cached.get("audio")
        transcript = cached.get("transcript")
        transcript_meta = cached.get("transcription")
        chat_features = cached.get("chat")
        chat_info = cached.get("chat_info")
        cache_from = dict(cached.get("from") or {})
        log_event(
            "cache.reuse",
            reuse_enabled=bool(reuse_features),
            reused_stages=sorted(cache_from),
        )

        need_audio = audio_features is None
        need_transcript = transcript is None
        prepared_model: PreparedModelReference | None = None

        with diagnostic_stage("model_resolution"):
            if skip_transcription:
                transcript = []
                transcript_meta = skipped_transcription_metadata(
                    settings.whisper_model,
                    SKIP_REASON_USER_REQUESTED,
                )
                cache_from.pop("transcript", None)
                need_transcript = False
                log_detailed("model.resolution", decision="user_skipped")
            elif need_transcript:
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
                    log_detailed("model.resolution", decision="downloads_disabled")
                else:
                    log_detailed(
                        "model.resolution",
                        decision="resolved",
                        model_name=safe_model_name(prepared_model.display_name, prepared_model.source),
                        model_source=prepared_model.source,
                        local_files_only=prepared_model.local_files_only,
                    )
            else:
                log_detailed("model.resolution", decision="cached_transcript")

        # The run is now committed to proceed. Consume the one-shot flag only here,
        # after any ModelDecisionRequired interaction has been resolved.
        if detailed_requested:
            consume_detailed_diagnostics_next_run(db_path)
            log_detailed("diagnostics.one_shot_consumed", next_mode="standard")

        transcription_skipped = is_transcription_skipped(transcript_meta)
        skip_reason = str((transcript_meta or {}).get("reason") or "") if transcription_skipped else None
        need_wav = need_audio or need_transcript

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
            stage_started_at = time.perf_counter()
            with diagnostic_stage("audio_extract"):
                extract_analysis_audio(video, wav)
            timings["audio_extract_seconds"] = _elapsed_since(stage_started_at)
        elif transcription_skipped:
            progress("Speech recognition disabled; using available signals", 0.16)
        else:
            progress("Reusing cached analysis audio features + transcript", 0.16)

        if need_audio:
            progress("Analyzing audio energy", 0.20)
            assert wav is not None
            stage_started_at = time.perf_counter()
            with diagnostic_stage("audio_analysis"):
                audio_features = analyze_audio(wav, settings.audio_window_sec, settings.audio_hop_sec)
            timings["audio_analysis_seconds"] = _elapsed_since(stage_started_at)
        else:
            progress("Reusing cached audio features", 0.24)
        log_detailed("signal.statistics", signal="audio", statistics=signal_statistics(list(audio_features or [])))

        if need_transcript:
            progress("Preparing faster-whisper transcription", _TRANSCRIPTION_PROGRESS_START)
            assert wav is not None
            assert prepared_model is not None
            stage_started_at = time.perf_counter()

            def transcription_progress(message: str, fraction: float) -> None:
                progress(message, _map_transcription_progress(fraction))

            with diagnostic_stage("transcription"):
                transcript, transcript_meta = transcribe_audio(
                    wav,
                    settings,
                    model_access=model_access,
                    prepared_model=prepared_model,
                    audio_duration=duration,
                    progress=transcription_progress,
                )
            timings["transcription_seconds"] = _elapsed_since(stage_started_at)
        elif transcription_skipped:
            progress("Skipping speech recognition", 0.60)
        else:
            progress("Reusing cached Whisper transcript", 0.60)

        transcript = _rescore_transcript(list(transcript or []), settings)
        transcript_meta = dict(transcript_meta or {})
        if not transcription_skipped:
            transcript_meta.setdefault("status", TRANSCRIPTION_AVAILABLE)
            transcript_meta["reaction_scoring"] = "current-settings"
        _log_model_metadata(transcript_meta, settings)
        log_detailed("signal.statistics", signal="transcript", statistics=signal_statistics(transcript))

        if chat_path:
            validated_chat = validate_chat_file(chat_path)
            if chat_features is None:
                progress("Parsing chat", _TRANSCRIPTION_PROGRESS_END)
                stage_started_at = time.perf_counter()
                with diagnostic_stage("chat_analysis"):
                    records = load_chat(validated_chat)
                    chat_features = analyze_chat(records, duration)
                timings["chat_analysis_seconds"] = _elapsed_since(stage_started_at)
                chat_info = {
                    "path": str(validated_chat),
                    "messages": len(records),
                }
            else:
                progress("Reusing cached chat features", 0.78)
                chat_info = dict(chat_info or {})
                chat_info["path"] = str(validated_chat)
        else:
            chat_features = []
            chat_info = {"path": None, "messages": 0}
        log_detailed("signal.statistics", signal="chat", statistics=signal_statistics(list(chat_features or [])))

        progress("Ranking candidate moments", 0.84)
        stage_started_at = time.perf_counter()
        with diagnostic_stage("candidate_ranking"):
            candidates = find_candidates(
                duration,
                list(audio_features or []),
                transcript,
                list(chat_features or []),
                settings,
                transcript_available=not transcription_skipped,
            )
        timings["candidate_ranking_seconds"] = _elapsed_since(stage_started_at)
        for candidate in candidates:
            candidate["content_label"] = normalized_content_label
            features = dict(candidate.get("features") or {})
            features["context"] = {
                "content_label": normalized_content_label,
                "mining_profile": mining_profile,
                "has_transcript": not transcription_skipped,
            }
            candidate["features"] = features
        log_event("candidates.generated", count=len(candidates))

        learning_info: dict = {
            "active": False,
            "state": "warming_up",
            "reason": "Preference learner has not been prepared yet.",
            "content_label": normalized_content_label,
            "mining_profile": mining_profile,
        }
        learning_started_at = time.perf_counter()
        progress("Applying personal reranker", 0.92)
        with diagnostic_stage("personal_rerank"):
            try:
                log_detailed("database.operation", operation="prepare_preference_model")
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
                log_detailed(
                    "learning.decision",
                    state=str(learning_info.get("state") or "unknown"),
                    active=bool(learning_info.get("active")),
                    reused_existing_model=bool(learning_info.get("reused_existing_model")),
                    blend_weight=float(learning_info.get("blend_weight") or 0.0),
                    category_applied_candidates=int(learning_info.get("category_applied_candidates") or 0),
                )
            except Exception as exc:
                # Preference learning is deliberately fail-open. Persist its normal
                # UI reason, but logs only get the sanitized stack and error type.
                learning_info = {
                    "active": False,
                    "state": "error",
                    "reason": f"Learner disabled for this run: {type(exc).__name__}: {exc}",
                    "content_label": normalized_content_label,
                    "mining_profile": mining_profile,
                }
                log_exception("learning.error", exc)
                log_detailed("learning.decision", state="error", active=False, error_type=type(exc).__name__)
        timings["personal_rerank_seconds"] = _elapsed_since(learning_started_at)

        timings["pipeline_elapsed_seconds"] = _elapsed_since(pipeline_started_at)
        cache_info = {
            "reused": cache_from,
            "reused_stages": sorted(cache_from),
            "reuse_enabled": bool(reuse_features),
            "mining_profile": mining_profile,
            "learning": learning_info,
            "transcription_skipped": transcription_skipped,
            "transcription_skip_reason": skip_reason,
            "timings": timings,
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
        progress("Saving analysis database", 0.97)
        save_signatures: dict[str, str | None] = dict(signatures)
        if transcription_skipped:
            save_signatures["transcript"] = None
        log_detailed("database.operation", operation="save_analysis")
        with diagnostic_stage("database_save"):
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
        log_event(
            "analysis.complete",
            duration_seconds=_elapsed_since(pipeline_started_at),
            candidate_count=len(candidates),
            reused_stages=sorted(cache_from),
        )
        return analysis_id
    except ModelDecisionRequired:
        log_event("analysis.model_decision_required", level=logging.WARNING)
        raise
    except Exception as exc:
        log_exception("analysis.error", exc, duration_seconds=_elapsed_since(pipeline_started_at))
        raise
    finally:
        if wav is not None:
            try:
                wav.unlink(missing_ok=True)
            except OSError:
                pass
        if detailed_started:
            stop_detailed_run()
