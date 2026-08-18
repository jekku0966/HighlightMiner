# HighlightMiner personal preference learning

This document describes the experimental learner on the `v0.2-learning` branch. The branch is based on `v0.2-dev`; the stable heuristic detector remains the safety net and candidate generator.

## Core contract

- **Keep = 1** positive example.
- **Reject = 0** negative example.
- **Unreviewed = unlabeled** and is not used as a negative.
- Existing analyses are never rewritten when a model changes.
- `candidates.score` remains the immutable base heuristic score.
- Learning only reranks candidates found by the heuristic detector.
- If learner training/prediction fails, HighlightMiner keeps the base ranking and continues the analysis.
- Speech recognition is optional; the learner records whether the transcript signal actually existed for each candidate.

The current model is a deterministic NumPy logistic regression with standardization and L2 regularization. It adds no scikit-learn, LLM, cloud, GPU-training, or Whisper fine-tuning dependency.

## Activation gates

The global personal reranker does not activate until all of these are true:

- at least **30** labeled candidates total;
- at least **8 Keep** examples;
- at least **8 Reject** examples;
- labels span at least **3 source VODs**.

Repeated reruns of one source are source-balanced so they cannot dominate merely because the same VOD was analyzed many times.

Learning influence starts at **10%**, grows with more labels, and is capped at **35%**. The base heuristic therefore always contributes at least 65% of the final ranking score.

## Learner features

The current `preference-logreg-v3-signal-availability` model uses information that already exists when the candidate is generated:

1. immutable base heuristic score;
2. audio score;
3. transcript/reaction score;
4. chat score;
5. candidate duration;
6. peak combined signal;
7. top-five combined mean;
8. active-signal fraction;
9. whether a transcript signal was available;
10. whether chat exists;
11. seed-point count;
12. effective normalized audio weight;
13. effective normalized transcript weight;
14. effective normalized chat weight.

The active-signal fraction is divided by the number of signals that actually existed for that candidate. A no-transcript run is therefore not penalized as though an inactive transcript signal had been present.

Older learning examples that predate explicit signal-availability tracking default to transcript-available because those builds always attempted Whisper when creating a fresh candidate set. The model-version bump prevents an older persisted 13-feature learner from being used as though it were compatible with this 14-feature schema.

Previous learner probabilities/final scores, review state, exports, clip titles, and other post-decision data are excluded from the feature vector to prevent target leakage.

## Optional speech recognition

When a user declines recognition-model downloads and no cached/local model is available, HighlightMiner can still create candidates using audio plus optional chat. The unavailable transcript gets zero effective weight and the remaining signals are renormalized before scoring.

Candidate snapshots record `has_transcript` plus the effective post-renormalization weights. This lets learning distinguish:

- `transcript_score = 0` because Whisper ran but found no reaction evidence; from
- `transcript_score = 0` because speech recognition was not part of that analysis at all.

A deliberately skipped transcript is not saved under the normal reusable Whisper cache signature, so a later transcript-enabled rerun can still reuse an older compatible valid transcript.

## Category / game context

`Content / Game` is part of the learning context. The global model still works for every category, including a category the user has never reviewed before.

A category-specific adjustment activates only after that category has enough evidence:

- at least **20** labeled candidates in the category;
- at least **5 Keep** and **5 Reject**;
- labels span at least **2 source VODs**.

The adjustment is a small, shrunk calibration bias layered on the global keep probability rather than an independent per-game model. It starts conservatively and is capped at 35% category-context strength. This avoids turning a handful of clips from one game into a wildly overfit model.

Blank/`Unsorted` categories do not receive category-specific adjustment; they still use the global learner.

## Mining-profile context

Every new analysis records the human-friendly mining profile used for that run:

- Balanced
- Reaction-heavy
- Chat-heavy
- Audio-heavy
- Custom

The profile name is provenance and diagnostics. The model uses the **actual normalized numeric signal weights** as inputs because they describe what the detector really did. When a signal is unavailable, the candidate stores the effective renormalized weights used for that run rather than pretending the original configured ratio was still active.

Two profiles that resolve to the same effective weights therefore look the same to the numeric model even if one is named `Custom`.

The profile name is still retained in the training fingerprint/model statistics so the UI can later answer questions such as:

- how many labels came from each profile;
- keep rate by profile;
- whether the dataset is heavily biased toward one mining configuration.

The learner does not currently apply a separate categorical "Reaction-heavy = good" bonus. That is deliberate; it prevents profile choice from becoming an easy spurious shortcut.

## Per-candidate ranking record

When learning is active, a candidate retains both detector and learner information in `features_json`:

```text
base score
base rank
global personal keep probability
category-adjusted keep probability
learning blend weight
final ranking score
model id/version
content/category
category-adjustment strength/label count
mining profile
transcript/chat availability
effective signal weights
```

The base score is never overwritten. New analysis runs can therefore be audited later: heuristic vs personal learner vs final blended ranking.

## Model persistence

Models are stored in SQLite in `preference_models`. Training is lazy: before a new analysis run, HighlightMiner fingerprints the current labeled dataset and reuses an existing identical model when possible. A new model is trained only when the relevant labeled dataset/context changes.

New analyses store the mining profile and transcript availability in candidate context. Older v0.2 analyses can reconstruct the profile from their exact saved settings snapshot and are treated as transcript-available for feature compatibility, so they remain useful learning data without a destructive migration.

## Current non-goals

- no Whisper fine-tuning;
- no LLM calls;
- no GPU model training;
- no automatic labeling of Unreviewed;
- no independent per-game model yet;
- no mining-profile categorical bonus yet;
- no automatic profile selection yet;
- no timing-adjustment learner yet.

Those can be evaluated after real Keep/Reject data exists and the conservative reranker can be measured against the base detector.
