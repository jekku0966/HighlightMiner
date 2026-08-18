from __future__ import annotations

from pathlib import Path

import pytest

from highlightminer.config import Settings
from highlightminer.model_access import (
    ModelAccessPreferences,
    ModelDecisionRequired,
    load_model_access,
    model_signature_payload,
    prepare_model_reference,
    resolve_model_reference,
    save_model_access,
    validate_local_model_directory,
)
from highlightminer.settings_store import import_app_settings


def _make_local_model(root: Path) -> Path:
    model = root / "local-model"
    model.mkdir()
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (model / name).write_bytes(b"test")
    return model


def test_model_download_consent_defaults_to_unset_and_persists(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    assert load_model_access(db).download_consent == "unset"

    saved = save_model_access(ModelAccessPreferences("deny", None), db)

    assert saved.download_consent == "deny"
    assert load_model_access(db).download_consent == "deny"


def test_imported_settings_cannot_grant_model_download_consent(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    save_model_access(ModelAccessPreferences("deny", None), db)
    profile = tmp_path / "settings.json"
    profile.write_text(
        '{"whisper_model":"small","allow_custom_whisper_model":false,"download_consent":"allow"}',
        encoding="utf-8",
    )

    import_app_settings(profile, db)

    assert load_model_access(db).download_consent == "deny"


def test_local_model_directory_requires_complete_ctranslate2_files(tmp_path: Path) -> None:
    model = tmp_path / "broken-model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="model.bin"):
        validate_local_model_directory(model)


def test_local_model_is_forced_offline_and_part_of_cache_signature(tmp_path: Path) -> None:
    model = _make_local_model(tmp_path)
    settings = Settings(whisper_model="large-v3")
    preferences = ModelAccessPreferences("allow", str(model))

    prepared = prepare_model_reference(settings, preferences)
    signature = model_signature_payload(settings, preferences)

    assert prepared.reference == str(model.resolve())
    assert prepared.local_files_only is True
    assert prepared.source == "local"
    assert signature["source"] == "local"
    assert signature["files"]["model.bin"]["size"] == 4


def test_uncached_model_requires_a_decision_when_policy_is_unset() -> None:
    settings = Settings(whisper_model="large-v3")
    calls: list[tuple[str, bool]] = []

    def fake_download(model: str, *, local_files_only: bool) -> str:
        calls.append((model, local_files_only))
        raise FileNotFoundError("not cached")

    with pytest.raises(ModelDecisionRequired, match="continue this analysis without speech recognition"):
        resolve_model_reference(
            settings,
            ModelAccessPreferences("unset", None),
            download_model_fn=fake_download,
        )

    assert calls == [("large-v3", True)]


def test_denied_uncached_model_resolves_to_no_transcription() -> None:
    prepared = resolve_model_reference(
        Settings(whisper_model="large-v3"),
        ModelAccessPreferences("deny", None),
        download_model_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    assert prepared is None


def test_cached_model_is_used_offline_even_without_download_consent(tmp_path: Path) -> None:
    cached = _make_local_model(tmp_path)
    prepared = resolve_model_reference(
        Settings(whisper_model="large-v3"),
        ModelAccessPreferences("unset", None),
        download_model_fn=lambda *_args, **_kwargs: str(cached),
    )

    assert prepared is not None
    assert prepared.reference == str(cached)
    assert prepared.local_files_only is True
    assert prepared.source == "cache"


def test_allowed_model_can_use_managed_download_path() -> None:
    prepared = resolve_model_reference(
        Settings(whisper_model="large-v3"),
        ModelAccessPreferences("allow", None),
        download_model_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    assert prepared is not None
    assert prepared.reference == "large-v3"
    assert prepared.local_files_only is False
    assert prepared.source == "managed"


def test_strict_prepare_still_blocks_denied_uncached_model() -> None:
    with pytest.raises(RuntimeError, match="model downloading is disabled"):
        prepare_model_reference(
            Settings(whisper_model="large-v3"),
            ModelAccessPreferences("deny", None),
            download_model_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
        )


def test_cache_probe_does_not_hide_unexpected_errors() -> None:
    def unreadable_cache(*_args, **_kwargs) -> str:
        raise PermissionError("cache unreadable")

    with pytest.raises(PermissionError, match="cache unreadable"):
        resolve_model_reference(
            Settings(whisper_model="large-v3"),
            ModelAccessPreferences("unset", None),
            download_model_fn=unreadable_cache,
        )
