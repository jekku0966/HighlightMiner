from __future__ import annotations

from pathlib import Path

import pytest

from highlightminer.config import Settings
from highlightminer.model_access import (
    ModelAccessPreferences,
    load_model_access,
    model_signature_payload,
    prepare_model_reference,
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


def test_uncached_model_is_blocked_without_explicit_consent() -> None:
    settings = Settings(whisper_model="large-v3")
    calls: list[tuple[str, bool]] = []

    def fake_download(model: str, *, local_files_only: bool) -> str:
        calls.append((model, local_files_only))
        raise FileNotFoundError("not cached")

    with pytest.raises(RuntimeError, match="explicitly allow model downloads"):
        prepare_model_reference(
            settings,
            ModelAccessPreferences("deny", None),
            download_model_fn=fake_download,
        )

    assert calls == [("large-v3", True)]


def test_allowed_model_can_use_managed_download_path() -> None:
    prepared = prepare_model_reference(
        Settings(whisper_model="large-v3"),
        ModelAccessPreferences("allow", None),
        download_model_fn=lambda *args, **kwargs: pytest.fail("cache lookup should not run"),
    )

    assert prepared.reference == "large-v3"
    assert prepared.local_files_only is False
    assert prepared.source == "managed"
