import json
from pathlib import Path

from highlightminer.config import Settings
from highlightminer.settings_presets import WEIGHT_PRESETS, detect_weight_preset, normalize_weights
from highlightminer.settings_store import export_app_settings, import_app_settings, load_app_settings, save_app_settings
from highlightminer.storage import connect


def test_weight_presets_normalize_and_detect() -> None:
    for name, weights in WEIGHT_PRESETS.items():
        normalized = normalize_weights(weights)
        assert abs(sum(normalized.values()) - 1.0) < 1e-9
        assert detect_weight_preset(weights) == name

    assert detect_weight_preset({"audio": 0.4, "transcript": 0.4, "chat": 0.2}) == "Custom"
    no_chat = normalize_weights(WEIGHT_PRESETS["Balanced"], chat_available=False)
    assert no_chat["chat"] == 0.0
    assert abs(no_chat["audio"] + no_chat["transcript"] - 1.0) < 1e-9


def test_app_settings_roundtrip_import_export(tmp_path: Path) -> None:
    db = tmp_path / "highlightminer.db"
    custom = Settings(
        whisper_model="large-v3",
        weights={"audio": 0.6, "transcript": 0.25, "chat": 0.15},
        reaction_phrases=["nice", "holy shit"],
        max_candidates=55,
    )
    save_app_settings(custom, db)

    loaded = load_app_settings(db)
    assert loaded.max_candidates == 55
    assert loaded.reaction_phrases == ["nice", "holy shit"]
    assert detect_weight_preset(loaded.weights) == "Audio-heavy"

    with connect(db) as conn:
        row = conn.execute("SELECT preset_name FROM app_settings WHERE id = 1").fetchone()
        assert row["preset_name"] == "Audio-heavy"

    exported = export_app_settings(tmp_path / "backup", db)
    assert exported.name == "backup.json"
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert payload["max_candidates"] == 55

    payload["max_candidates"] = 12
    imported_path = tmp_path / "import.json"
    imported_path.write_text(json.dumps(payload), encoding="utf-8")
    imported = import_app_settings(imported_path, db)
    assert imported.max_candidates == 12
    assert load_app_settings(db).max_candidates == 12
