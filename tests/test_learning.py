from __future__ import annotations

import random

from highlightminer.learning import (
    MIN_CATEGORY_LABELED,
    MIN_LABELED,
    PreferenceModel,
    feature_vector,
    predict_keep_probability,
    predict_keep_probability_details,
    rerank_candidates,
    train_preference_model,
    training_fingerprint,
)


def _example(
    i: int,
    label: int,
    source: str,
    *,
    category: str = "Overwatch 2",
    profile: str = "Balanced",
    weights: tuple[float, float, float] = (0.34, 0.42, 0.24),
) -> dict:
    strong = float(label)
    jitter = (i % 5) * 0.01
    return {
        "analysis_id": f"a{i:03d}",
        "candidate_id": f"H{i:03d}",
        "source_id": source,
        "label": label,
        "content_label": category,
        "mining_profile": profile,
        "mining_weights": {"audio": weights[0], "transcript": weights[1], "chat": weights[2]},
        "base_score": 0.45 + 0.15 * strong + jitter,
        "audio_score": 0.25 + 0.55 * strong,
        "transcript_score": 0.20 + 0.65 * strong,
        "chat_score": 0.15 + 0.55 * strong,
        "features": {
            "candidate_duration": 28 + 8 * strong,
            "peak_combined": 0.40 + 0.45 * strong,
            "top5_combined_mean": 0.35 + 0.42 * strong,
            "active_signal_count": 1 + 2 * label,
            "has_chat": True,
            "seed_points": 3 + 8 * label,
            "weight_audio": weights[0],
            "weight_transcript": weights[1],
            "weight_chat": weights[2],
            "learning": {"final_score": 1.0 - strong, "keep_probability": 1.0 - strong},
        },
    }


def _training_examples() -> list[dict]:
    rows = []
    for i in range(18):
        rows.append(_example(i, 1, f"source-{i % 4}"))
    for i in range(18, 36):
        rows.append(_example(i, 0, f"source-{i % 4}"))
    return rows


def test_warmup_does_not_activate_too_early() -> None:
    rows = _training_examples()[: MIN_LABELED - 1]
    result = train_preference_model(rows)
    assert result.state == "warming_up"
    assert result.model is None


def test_model_roundtrip_prediction_and_fingerprint_are_deterministic() -> None:
    rows = _training_examples()
    shuffled = rows[:]
    random.Random(123).shuffle(shuffled)
    assert training_fingerprint(rows) == training_fingerprint(shuffled)

    result = train_preference_model(rows)
    assert result.state == "active"
    assert result.model is not None
    restored = PreferenceModel.from_dict(result.model.to_dict())
    keep_probability = predict_keep_probability(restored, _example(90, 1, "new-source"))
    reject_probability = predict_keep_probability(restored, _example(91, 0, "new-source"))
    assert keep_probability > reject_probability
    assert 0.0 < restored.blend_weight <= 0.35


def test_feature_vector_ignores_previous_learning_output_and_keeps_mining_weights() -> None:
    row = _example(1, 1, "s", weights=(0.20, 0.60, 0.20), profile="Reaction-heavy")
    first = feature_vector(row)
    assert first[-3:].tolist() == [0.2, 0.6, 0.2]
    row["features"]["learning"]["final_score"] = 0.001
    row["features"]["learning"]["keep_probability"] = 0.001
    second = feature_vector(row)
    assert first.tolist() == second.tolist()


def test_reranking_preserves_base_score_and_records_context() -> None:
    model = train_preference_model(_training_examples()).model
    assert model is not None
    candidates = [
        {
            "id": "H001",
            "rank": 1,
            "score": 0.70,
            "audio_score": 0.20,
            "transcript_score": 0.20,
            "chat_score": 0.20,
            "features": {
                "candidate_duration": 25,
                "peak_combined": 0.45,
                "top5_combined_mean": 0.40,
                "active_signal_count": 1,
                "has_chat": True,
                "seed_points": 3,
                "weight_audio": 0.2,
                "weight_transcript": 0.6,
                "weight_chat": 0.2,
            },
        },
        {
            "id": "H002",
            "rank": 2,
            "score": 0.66,
            "audio_score": 0.85,
            "transcript_score": 0.88,
            "chat_score": 0.80,
            "features": {
                "candidate_duration": 34,
                "peak_combined": 0.86,
                "top5_combined_mean": 0.82,
                "active_signal_count": 3,
                "has_chat": True,
                "seed_points": 12,
                "weight_audio": 0.2,
                "weight_transcript": 0.6,
                "weight_chat": 0.2,
            },
        },
    ]
    ranked, info = rerank_candidates(
        candidates,
        model,
        model_id="model-123",
        content_label="Overwatch 2",
        mining_profile="Reaction-heavy",
    )
    assert info["active"] is True
    assert {row["score"] for row in ranked} == {0.70, 0.66}
    assert ranked[0]["features"]["learning"]["model_id"] == "model-123"
    assert ranked[0]["features"]["learning"]["base_score"] in {0.70, 0.66}
    assert ranked[0]["features"]["learning"]["mining_profile"] == "Reaction-heavy"
    assert ranked[0]["features"]["context"]["content_label"] == "Overwatch 2"
    assert ranked[0]["id"] == "H001"
    assert ranked[1]["id"] == "H002"


def test_category_adjustment_requires_enough_data_and_then_changes_probability() -> None:
    rows: list[dict] = []
    for i in range(40):
        rows.append(_example(i, i % 2, f"global-{i % 4}", category="Just Chatting"))

    start = 100
    for i in range(MIN_CATEGORY_LABELED + 4):
        label = 0 if i < 5 else 1
        rows.append(_example(start + i, label, f"horror-{i % 3}", category="Horror"))

    model = train_preference_model(rows).model
    assert model is not None
    assert "Horror" in model.category_adjustments

    probe = _example(999, 1, "new", category="Horror")
    adjusted, detail = predict_keep_probability_details(model, probe)
    probe["content_label"] = "Unseen Game"
    plain, plain_detail = predict_keep_probability_details(model, probe)
    assert detail["category_adjustment_active"] is True
    assert plain_detail["category_adjustment_active"] is False
    assert adjusted > plain


def test_profile_is_provenance_while_numeric_weights_are_model_input() -> None:
    a = _example(1, 1, "s", profile="Reaction-heavy", weights=(0.20, 0.60, 0.20))
    b = _example(1, 1, "s", profile="Custom", weights=(0.20, 0.60, 0.20))
    assert feature_vector(a).tolist() == feature_vector(b).tolist()
    assert training_fingerprint([a]) != training_fingerprint([b])
