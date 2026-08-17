from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np

MODEL_VERSION = "preference-logreg-v2-context"
MIN_LABELED = 30
MIN_PER_CLASS = 8
MIN_SOURCES = 3
MAX_BLEND_WEIGHT = 0.35
START_BLEND_WEIGHT = 0.10
FULL_BLEND_AT = 150
L2_REGULARIZATION = 0.20
MAX_STEPS = 1200
LEARNING_RATE = 0.08
TOLERANCE = 1e-7

MIN_CATEGORY_LABELED = 20
MIN_CATEGORY_PER_CLASS = 5
MIN_CATEGORY_SOURCES = 2
MAX_CATEGORY_STRENGTH = 0.35
FULL_CATEGORY_STRENGTH_AT = 80
CATEGORY_PRIOR_STRENGTH = 12.0

FEATURE_NAMES = (
    "base_score",
    "audio_score",
    "transcript_score",
    "chat_score",
    "candidate_duration_log",
    "peak_combined",
    "top5_combined_mean",
    "active_signal_fraction",
    "has_chat",
    "seed_points_log",
    "weight_audio",
    "weight_transcript",
    "weight_chat",
)


@dataclass(frozen=True)
class PreferenceModel:
    model_version: str
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    labeled_count: int
    positive_count: int
    negative_count: int
    source_count: int
    blend_weight: float
    training_fingerprint: str
    metrics: dict[str, float]
    category_adjustments: dict[str, dict[str, Any]]
    profile_stats: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["feature_names"] = list(self.feature_names)
        payload["means"] = list(self.means)
        payload["scales"] = list(self.scales)
        payload["coefficients"] = list(self.coefficients)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PreferenceModel":
        return cls(
            model_version=str(payload["model_version"]),
            feature_names=tuple(payload["feature_names"]),
            means=tuple(float(x) for x in payload["means"]),
            scales=tuple(float(x) for x in payload["scales"]),
            coefficients=tuple(float(x) for x in payload["coefficients"]),
            intercept=float(payload["intercept"]),
            labeled_count=int(payload["labeled_count"]),
            positive_count=int(payload["positive_count"]),
            negative_count=int(payload["negative_count"]),
            source_count=int(payload["source_count"]),
            blend_weight=float(payload["blend_weight"]),
            training_fingerprint=str(payload["training_fingerprint"]),
            metrics={str(k): float(v) for k, v in dict(payload.get("metrics") or {}).items()},
            category_adjustments={str(k): dict(v) for k, v in dict(payload.get("category_adjustments") or {}).items()},
            profile_stats={str(k): dict(v) for k, v in dict(payload.get("profile_stats") or {}).items()},
        )


@dataclass(frozen=True)
class TrainingResult:
    state: str
    reason: str
    model: PreferenceModel | None
    labeled_count: int
    positive_count: int
    negative_count: int
    source_count: int
    training_fingerprint: str | None = None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _normalized_context_weights(item: dict[str, Any], features: dict[str, Any]) -> tuple[float, float, float]:
    weights = dict(item.get("mining_weights") or {})
    audio = _safe_float(features.get("weight_audio", weights.get("audio", 0.0)))
    transcript = _safe_float(features.get("weight_transcript", weights.get("transcript", 0.0)))
    chat = _safe_float(features.get("weight_chat", weights.get("chat", 0.0)))
    total = max(0.0, audio) + max(0.0, transcript) + max(0.0, chat)
    if total <= 0.0:
        return 0.0, 0.0, 0.0
    return max(0.0, audio) / total, max(0.0, transcript) / total, max(0.0, chat) / total


def feature_vector(item: dict[str, Any]) -> np.ndarray:
    """Extract stable learner features from a candidate/example.

    Numeric mining weights are model inputs. The human-friendly profile name is
    retained as provenance/diagnostics and is not a categorical shortcut.
    Previous learner output is deliberately ignored to prevent self-training.
    """
    features = dict(item.get("features") or {})
    base_score = _safe_float(item.get("base_score", item.get("score", 0.0)))
    audio = _safe_float(item.get("audio_score", features.get("max_audio", 0.0)))
    transcript = _safe_float(item.get("transcript_score", features.get("max_transcript", 0.0)))
    chat = _safe_float(item.get("chat_score", features.get("max_chat", 0.0)))
    duration = max(0.0, _safe_float(features.get("candidate_duration", item.get("original_duration", 0.0))))
    peak = _safe_float(features.get("peak_combined", base_score))
    top5 = _safe_float(features.get("top5_combined_mean", base_score))
    active = min(3.0, max(0.0, _safe_float(features.get("active_signal_count", 0.0)))) / 3.0
    has_chat = 1.0 if bool(features.get("has_chat", chat > 0.0)) else 0.0
    seed_points = max(0.0, _safe_float(features.get("seed_points", 0.0)))
    weight_audio, weight_transcript, weight_chat = _normalized_context_weights(item, features)

    return np.asarray(
        [
            base_score,
            audio,
            transcript,
            chat,
            math.log1p(duration),
            peak,
            top5,
            active,
            has_chat,
            math.log1p(seed_points),
            weight_audio,
            weight_transcript,
            weight_chat,
        ],
        dtype=np.float64,
    )


def _category(item: dict[str, Any]) -> str:
    value = str(item.get("content_label") or "").strip()
    return value if value and value.casefold() != "unsorted" else ""


def _profile(item: dict[str, Any]) -> str:
    value = str(item.get("mining_profile") or "Custom").strip()
    return value or "Custom"


def training_fingerprint(examples: Iterable[dict[str, Any]]) -> str:
    rows = []
    for example in examples:
        label = example.get("label")
        if label not in (0, 1):
            continue
        rows.append(
            {
                "analysis_id": str(example.get("analysis_id") or ""),
                "candidate_id": str(example.get("candidate_id") or ""),
                "source_id": str(example.get("source_id") or example.get("analysis_id") or ""),
                "label": int(label),
                "category": _category(example),
                "mining_profile": _profile(example),
                "features": [round(float(x), 8) for x in feature_vector(example)],
            }
        )
    rows.sort(key=lambda row: (row["analysis_id"], row["candidate_id"], row["label"]))
    payload = json.dumps(
        {"model_version": MODEL_VERSION, "features": FEATURE_NAMES, "examples": rows},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _blend_weight(labeled_count: int) -> float:
    if labeled_count < MIN_LABELED:
        return 0.0
    span = max(1, FULL_BLEND_AT - MIN_LABELED)
    progress = min(1.0, max(0.0, (labeled_count - MIN_LABELED) / span))
    return START_BLEND_WEIGHT + progress * (MAX_BLEND_WEIGHT - START_BLEND_WEIGHT)


def _source_and_class_weights(examples: list[dict[str, Any]], y: np.ndarray) -> np.ndarray:
    sources = [str(ex.get("source_id") or ex.get("analysis_id") or f"row-{i}") for i, ex in enumerate(examples)]
    counts: dict[str, int] = {}
    for source in sources:
        counts[source] = counts.get(source, 0) + 1

    weights = np.asarray([1.0 / counts[source] for source in sources], dtype=np.float64)
    for label in (0.0, 1.0):
        mask = y == label
        total = float(weights[mask].sum())
        if total > 0:
            weights[mask] *= 0.5 / total
    mean = float(weights.mean())
    if mean > 0:
        weights /= mean
    return weights


def _source_weights(examples: list[dict[str, Any]]) -> np.ndarray:
    sources = [str(ex.get("source_id") or ex.get("analysis_id") or f"row-{i}") for i, ex in enumerate(examples)]
    counts: dict[str, int] = {}
    for source in sources:
        counts[source] = counts.get(source, 0) + 1
    weights = np.asarray([1.0 / counts[source] for source in sources], dtype=np.float64)
    mean = float(weights.mean()) if len(weights) else 0.0
    return weights / mean if mean > 0 else weights


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _logit(probability: float) -> float:
    p = min(1.0 - 1e-6, max(1e-6, float(probability)))
    return math.log(p / (1.0 - p))


def _binary_metrics(y: np.ndarray, probability: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    eps = 1e-9
    probability = np.clip(probability, eps, 1.0 - eps)
    weight_sum = max(eps, float(weights.sum()))
    log_loss = -float(np.sum(weights * (y * np.log(probability) + (1.0 - y) * np.log(1.0 - probability))) / weight_sum)
    brier = float(np.sum(weights * np.square(probability - y)) / weight_sum)
    predicted = probability >= 0.5
    positive = y == 1.0
    negative = ~positive
    tpr = float(np.mean(predicted[positive])) if np.any(positive) else 0.0
    tnr = float(np.mean(~predicted[negative])) if np.any(negative) else 0.0
    return {
        "balanced_accuracy_train": (tpr + tnr) / 2.0,
        "log_loss_train": log_loss,
        "brier_train": brier,
    }


def _context_stats(examples: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for example in examples:
        key = key_fn(example)
        if not key:
            continue
        grouped.setdefault(key, []).append(example)

    result: dict[str, dict[str, Any]] = {}
    for key, rows in grouped.items():
        positives = sum(int(row["label"]) == 1 for row in rows)
        negatives = len(rows) - positives
        sources = {str(row.get("source_id") or row.get("analysis_id") or "") for row in rows}
        weights = _source_weights(rows)
        labels = np.asarray([float(row["label"]) for row in rows], dtype=np.float64)
        keep_rate = float(np.average(labels, weights=weights)) if len(rows) else 0.0
        result[key] = {
            "labeled_count": len(rows),
            "positive_count": positives,
            "negative_count": negatives,
            "source_count": len(sources),
            "keep_rate": round(keep_rate, 6),
        }
    return result


def _category_adjustments(examples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats = _context_stats(examples, _category)
    weights = _source_weights(examples)
    labels = np.asarray([float(row["label"]) for row in examples], dtype=np.float64)
    global_keep = float(np.average(labels, weights=weights)) if len(examples) else 0.5

    result: dict[str, dict[str, Any]] = {}
    for category, stat in stats.items():
        labeled = int(stat["labeled_count"])
        positives = int(stat["positive_count"])
        negatives = int(stat["negative_count"])
        sources = int(stat["source_count"])
        if (
            labeled < MIN_CATEGORY_LABELED
            or positives < MIN_CATEGORY_PER_CLASS
            or negatives < MIN_CATEGORY_PER_CLASS
            or sources < MIN_CATEGORY_SOURCES
        ):
            continue

        shrunk_keep = (positives + CATEGORY_PRIOR_STRENGTH * global_keep) / (labeled + CATEGORY_PRIOR_STRENGTH)
        delta = _logit(shrunk_keep) - _logit(global_keep)
        span = max(1, FULL_CATEGORY_STRENGTH_AT - MIN_CATEGORY_LABELED)
        progress = min(1.0, max(0.0, (labeled - MIN_CATEGORY_LABELED) / span))
        strength = 0.10 + progress * (MAX_CATEGORY_STRENGTH - 0.10)
        result[category] = {
            **stat,
            "global_keep_rate": round(global_keep, 6),
            "shrunk_keep_rate": round(shrunk_keep, 6),
            "logit_delta": round(delta, 6),
            "strength": round(strength, 6),
        }
    return result


def train_preference_model(examples: Iterable[dict[str, Any]]) -> TrainingResult:
    labeled = [dict(ex) for ex in examples if ex.get("label") in (0, 1)]
    positives = sum(int(ex["label"]) == 1 for ex in labeled)
    negatives = len(labeled) - positives
    source_count = len({str(ex.get("source_id") or ex.get("analysis_id") or "") for ex in labeled})
    fingerprint = training_fingerprint(labeled) if labeled else None

    if len(labeled) < MIN_LABELED:
        return TrainingResult("warming_up", f"Need {MIN_LABELED - len(labeled)} more labeled candidates.", None, len(labeled), positives, negatives, source_count, fingerprint)
    if positives < MIN_PER_CLASS or negatives < MIN_PER_CLASS:
        return TrainingResult(
            "warming_up",
            f"Need at least {MIN_PER_CLASS} Keep and {MIN_PER_CLASS} Reject examples.",
            None,
            len(labeled),
            positives,
            negatives,
            source_count,
            fingerprint,
        )
    if source_count < MIN_SOURCES:
        return TrainingResult("warming_up", f"Need labels from at least {MIN_SOURCES} source VODs.", None, len(labeled), positives, negatives, source_count, fingerprint)

    x = np.vstack([feature_vector(ex) for ex in labeled])
    y = np.asarray([float(ex["label"]) for ex in labeled], dtype=np.float64)
    sample_weights = _source_and_class_weights(labeled, y)
    total_weight = float(sample_weights.sum())

    means = np.average(x, axis=0, weights=sample_weights)
    centered = x - means
    variances = np.average(np.square(centered), axis=0, weights=sample_weights)
    scales = np.sqrt(np.maximum(variances, 1e-8))
    scales = np.where(scales < 1e-4, 1.0, scales)
    z = centered / scales

    coefficients = np.zeros(z.shape[1], dtype=np.float64)
    intercept = 0.0
    for step in range(MAX_STEPS):
        probability = _sigmoid(z @ coefficients + intercept)
        error = (probability - y) * sample_weights
        grad_coef = (z.T @ error) / total_weight + L2_REGULARIZATION * coefficients
        grad_intercept = float(np.sum(error) / total_weight)

        rate = LEARNING_RATE / (1.0 + 0.0025 * step)
        coefficients -= rate * grad_coef
        intercept -= rate * grad_intercept
        if max(float(np.max(np.abs(grad_coef))), abs(grad_intercept)) < TOLERANCE:
            break

    probability = _sigmoid(z @ coefficients + intercept)
    metrics = _binary_metrics(y, probability, sample_weights)
    model = PreferenceModel(
        model_version=MODEL_VERSION,
        feature_names=FEATURE_NAMES,
        means=tuple(float(v) for v in means),
        scales=tuple(float(v) for v in scales),
        coefficients=tuple(float(v) for v in coefficients),
        intercept=float(intercept),
        labeled_count=len(labeled),
        positive_count=positives,
        negative_count=negatives,
        source_count=source_count,
        blend_weight=float(_blend_weight(len(labeled))),
        training_fingerprint=str(fingerprint),
        metrics=metrics,
        category_adjustments=_category_adjustments(labeled),
        profile_stats=_context_stats(labeled, _profile),
    )
    return TrainingResult("active", "Preference reranking is active.", model, len(labeled), positives, negatives, source_count, fingerprint)


def predict_keep_probability_details(model: PreferenceModel, item: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    if tuple(model.feature_names) != FEATURE_NAMES:
        raise ValueError("Preference model feature schema is incompatible with this HighlightMiner build.")
    vector = feature_vector(item)
    means = np.asarray(model.means, dtype=np.float64)
    scales = np.asarray(model.scales, dtype=np.float64)
    coefficients = np.asarray(model.coefficients, dtype=np.float64)
    z = (vector - means) / scales
    global_probability = float(_sigmoid(np.asarray([z @ coefficients + model.intercept]))[0])

    category = _category(item)
    adjustment = dict(model.category_adjustments.get(category) or {}) if category else {}
    if adjustment:
        delta = _safe_float(adjustment.get("logit_delta"))
        strength = min(MAX_CATEGORY_STRENGTH, max(0.0, _safe_float(adjustment.get("strength"))))
        probability = float(_sigmoid(np.asarray([_logit(global_probability) + strength * delta]))[0])
    else:
        probability = global_probability
        strength = 0.0

    return probability, {
        "global_keep_probability": round(global_probability, 6),
        "category": category or None,
        "category_adjustment_active": bool(adjustment),
        "category_strength": round(strength, 6),
        "category_labeled_count": int(adjustment.get("labeled_count", 0)) if adjustment else 0,
    }


def predict_keep_probability(model: PreferenceModel, item: dict[str, Any]) -> float:
    return predict_keep_probability_details(model, item)[0]


def rerank_candidates(
    candidates: Iterable[dict[str, Any]],
    model: PreferenceModel | None,
    *,
    model_id: str | None = None,
    content_label: str | None = None,
    mining_profile: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [dict(candidate) for candidate in candidates]
    if model is None or model.blend_weight <= 0.0:
        return rows, {
            "active": False,
            "model_id": model_id,
            "model_version": model.model_version if model else None,
            "blend_weight": 0.0,
            "content_label": content_label,
            "mining_profile": mining_profile,
        }

    blend = min(MAX_BLEND_WEIGHT, max(0.0, float(model.blend_weight)))
    enriched: list[dict[str, Any]] = []
    category_applied = 0
    for base_rank, candidate in enumerate(rows, start=1):
        base_score = _safe_float(candidate.get("score", 0.0))
        context_item = dict(candidate)
        if content_label:
            context_item["content_label"] = content_label
        if mining_profile:
            context_item["mining_profile"] = mining_profile
        probability, context = predict_keep_probability_details(model, context_item)
        final_score = (1.0 - blend) * base_score + blend * probability
        category_applied += int(bool(context["category_adjustment_active"]))

        features = dict(candidate.get("features") or {})
        features["context"] = {
            "content_label": content_label,
            "mining_profile": mining_profile or "Custom",
        }
        features["learning"] = {
            "model_id": model_id,
            "model_version": model.model_version,
            "base_rank": int(candidate.get("rank") or base_rank),
            "base_score": round(base_score, 6),
            "global_keep_probability": context["global_keep_probability"],
            "keep_probability": round(probability, 6),
            "blend_weight": round(blend, 6),
            "final_score": round(final_score, 6),
            "category": context["category"],
            "category_adjustment_active": context["category_adjustment_active"],
            "category_strength": context["category_strength"],
            "category_labeled_count": context["category_labeled_count"],
            "mining_profile": mining_profile or "Custom",
        }
        updated = dict(candidate)
        updated["features"] = features
        enriched.append(updated)

    enriched.sort(
        key=lambda candidate: (
            float(candidate["features"]["learning"]["final_score"]),
            float(candidate.get("score", 0.0)),
        ),
        reverse=True,
    )
    for rank, candidate in enumerate(enriched, start=1):
        candidate["rank"] = rank
        candidate["id"] = f"H{rank:03d}"

    return enriched, {
        "active": True,
        "model_id": model_id,
        "model_version": model.model_version,
        "blend_weight": blend,
        "labeled_count": model.labeled_count,
        "positive_count": model.positive_count,
        "negative_count": model.negative_count,
        "source_count": model.source_count,
        "category_adjustment_count": len(model.category_adjustments),
        "category_applied_candidates": category_applied,
        "content_label": content_label,
        "mining_profile": mining_profile,
        "metrics": dict(model.metrics),
    }
