from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .learning import PreferenceModel, TrainingResult, train_preference_model
from .settings_presets import detect_weight_preset, normalize_weights
from .storage import connect, learning_examples, utc_now


@dataclass(frozen=True)
class PreparedPreferenceModel:
    model_id: str | None
    model: PreferenceModel | None
    training: TrainingResult
    reused_existing_model: bool


def _ensure_table(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS preference_models (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL DEFAULT 'global',
            model_version TEXT NOT NULL,
            training_fingerprint TEXT NOT NULL,
            trained_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
            model_json TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_preference_models_fingerprint
            ON preference_models(scope, model_version, training_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_preference_models_active
            ON preference_models(scope, active, trained_at DESC);
        """
    )
    conn.commit()


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def learning_examples_with_context(
    db_path: str | Path | None = None,
    *,
    include_unreviewed: bool = True,
) -> list[dict[str, Any]]:
    """Enrich learning rows with category + mining-profile provenance.

    New runs persist the profile in cache/candidate context. Older v0.2 runs can
    reconstruct it from their exact settings snapshot, so historical data does
    not need to be rewritten merely to train the learner.
    """
    examples = learning_examples(db_path, include_unreviewed=include_unreviewed)
    if not examples:
        return []

    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, content_label, settings_json, cache_json FROM analyses"
        ).fetchall()

    context: dict[str, dict[str, Any]] = {}
    for row in rows:
        settings = _json_object(row["settings_json"])
        cache = _json_object(row["cache_json"])
        raw_weights = dict(settings.get("weights") or {})
        profile = str(cache.get("mining_profile") or "").strip()
        if not profile:
            try:
                profile = detect_weight_preset(raw_weights)
            except (TypeError, ValueError):
                profile = "Custom"
        try:
            weights = normalize_weights(raw_weights)
        except (TypeError, ValueError):
            weights = {"audio": 0.0, "transcript": 0.0, "chat": 0.0}
        context[str(row["id"])] = {
            "content_label": str(row["content_label"] or "Unsorted"),
            "mining_profile": profile or "Custom",
            "mining_weights": weights,
        }

    enriched: list[dict[str, Any]] = []
    for example in examples:
        item = dict(example)
        analysis_context = dict(context.get(str(item.get("analysis_id")), {}))
        feature_context = dict((item.get("features") or {}).get("context") or {})
        item.update(analysis_context)
        if feature_context.get("content_label"):
            item["content_label"] = str(feature_context["content_label"])
        if feature_context.get("mining_profile"):
            item["mining_profile"] = str(feature_context["mining_profile"])
        item.setdefault("mining_profile", "Custom")
        item.setdefault("mining_weights", {"audio": 0.0, "transcript": 0.0, "chat": 0.0})
        enriched.append(item)
    return enriched


def prepare_preference_model(db_path: str | Path | None = None) -> PreparedPreferenceModel:
    """Load/retrain the global personal reranker from Keep/Reject labels."""
    examples = learning_examples_with_context(db_path, include_unreviewed=False)
    training = train_preference_model(examples)
    if training.model is None:
        return PreparedPreferenceModel(None, None, training, False)

    model = training.model
    with connect(db_path) as conn:
        _ensure_table(conn)
        row = conn.execute(
            """
            SELECT id, model_json FROM preference_models
            WHERE scope = 'global' AND model_version = ? AND training_fingerprint = ?
            LIMIT 1
            """,
            (model.model_version, model.training_fingerprint),
        ).fetchone()
        if row is not None:
            loaded = PreferenceModel.from_dict(json.loads(row["model_json"]))
            model_id = str(row["id"])
            conn.execute(
                "UPDATE preference_models SET active = CASE WHEN id = ? THEN 1 ELSE 0 END WHERE scope = 'global'",
                (model_id,),
            )
            conn.commit()
            return PreparedPreferenceModel(model_id, loaded, training, True)

        model_id = uuid.uuid4().hex
        conn.execute("UPDATE preference_models SET active = 0 WHERE scope = 'global'")
        conn.execute(
            """
            INSERT INTO preference_models(
                id, scope, model_version, training_fingerprint, trained_at, active, model_json
            ) VALUES (?, 'global', ?, ?, ?, 1, ?)
            """,
            (
                model_id,
                model.model_version,
                model.training_fingerprint,
                utc_now(),
                json.dumps(model.to_dict(), ensure_ascii=False, separators=(",", ":")),
            ),
        )
        conn.commit()
        return PreparedPreferenceModel(model_id, model, training, False)


def load_active_preference_model(db_path: str | Path | None = None) -> tuple[str, PreferenceModel] | None:
    with connect(db_path) as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT id, model_json FROM preference_models WHERE scope = 'global' AND active = 1 ORDER BY trained_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return str(row["id"]), PreferenceModel.from_dict(json.loads(row["model_json"]))


def preference_learning_status(db_path: str | Path | None = None) -> dict[str, Any]:
    examples = learning_examples_with_context(db_path, include_unreviewed=False)
    training = train_preference_model(examples)
    active = load_active_preference_model(db_path)
    model = active[1] if active else training.model
    return {
        "state": training.state,
        "reason": training.reason,
        "labeled_count": training.labeled_count,
        "positive_count": training.positive_count,
        "negative_count": training.negative_count,
        "source_count": training.source_count,
        "active_model_id": active[0] if active else None,
        "active_model_version": active[1].model_version if active else (model.model_version if model else None),
        "active_blend_weight": active[1].blend_weight if active else (model.blend_weight if model else 0.0),
        "category_adjustments": dict(model.category_adjustments) if model else {},
        "profile_stats": dict(model.profile_stats) if model else {},
    }
