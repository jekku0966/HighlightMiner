# Same-VOD reruns and learning data

`v0.2-learning` keeps the `v0.2-dev` source/run architecture and adds an experimental personal reranker. Re-analyzing the same physical VOD creates a new run instead of overwriting history.

```text
source VOD
├── run 1
├── run 2
└── run 3
```

## Source identity

HighlightMiner uses a sampled SHA-256 identity built from file size plus samples from the beginning, middle, and end of the VOD. Filename/path are not part of the identity, so a byte-identical VOD can be moved or renamed and recognized when selected again.

This is an application identity key, **not an integrity/security hash**. Release integrity still uses full SHA-256 checksums.

## Rerunning a VOD

When **Analyze VOD** finds previous runs, the UI offers **Load latest** or **Analyze again**. A **Force full reprocess** checkbox disables cache reuse for the new run.

A rerun always performs candidate ranking again. Compatible expensive stages can be reused independently:

- audio features: reused when audio window/hop and analysis-audio format match;
- Whisper transcript: reused when model/inference settings match;
- chat features: reused when the same chat file is supplied, verified with a full chat-file SHA-256.

`reaction_phrases` do not invalidate the Whisper transcript. Cached text is cheaply rescored with the current reaction phrases instead of retranscribing the VOD.

Model-download consent is evaluated **after** compatible transcript reuse. If a matching transcript already exists, HighlightMiner can rerank the VOD without asking for a model download or requiring the model to still be installed.

If a fresh transcript is required but speech recognition is deliberately skipped, the analysis stores `status = skipped` and a reason. The empty transcript is saved with **no Whisper cache signature**, so it cannot shadow an older compatible valid transcript. A later transcript-enabled rerun can still reuse that older valid data.

CLI full-reprocess equivalent:

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --no-reuse
```

The non-interactive CLI can explicitly allow a missing model download or skip transcription for one command:

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --allow-model-download
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --no-transcription
```

## Learning labels and retained context

Review states map to supervised learning as follows:

| State | Label |
|---|---:|
| Keep | `1` positive |
| Reject | `0` negative |
| Unreviewed | `None` / unlabeled |

**Unreviewed is not treated as Reject.** Not having judged a candidate is not negative preference evidence.

Candidate rows retain the original heuristic rank/score, audio/transcript/chat scores, combined-signal statistics, active-signal count, candidate duration, transcript/chat availability, effective scoring weights, content/game label, source/run IDs, algorithm version, and feature-schema version.

Every new learning-branch run also snapshots:

- the human-friendly mining profile (`Balanced`, `Reaction-heavy`, `Chat-heavy`, `Audio-heavy`, or `Custom`);
- the actual normalized signal weights used by the detector after unavailable signals are removed;
- whether the transcript signal was available;
- content/game category context;
- when active, the model ID/version, base rank/score, personal keep probability, category-adjustment metadata, learner blend weight, and final ranking score.

The learner therefore distinguishes a real transcript score of zero from a no-transcript run. Its active-signal fraction is normalized against the signals that actually existed rather than always assuming three signals were present.

The review layer also retains user-adjusted timing, title edits, review timestamps, meaningful review changes in `review_events`, and every export in `exports`.

## Reruns and training balance

Repeated analyses of the same source are useful for comparing settings and learner versions, but they must not dominate preference training simply because the same VOD was rerun many times. The global learner source-balances examples during fitting and requires labels from multiple source VODs before activation.

Category-specific context is also gated across multiple source VODs. A category does not receive its own calibration adjustment from a handful of clips on one stream.

The current learner does not yet explicitly cluster same-source temporal-overlap duplicates across reruns; source balancing limits one VOD's total influence but is not the same as deduplicating overlapping moments.

## Personal reranker behavior

The heuristic detector remains the candidate generator and safety net. Learning only changes the order of plausible candidates on **new** analysis runs; existing runs are never rewritten.

The global learner activates after at least 30 labeled candidates, at least 8 Keep + 8 Reject, and at least 3 source VODs. Influence starts at 10% and is capped at 35%.

The current model version includes explicit transcript availability in its feature schema. Persisted learner models from the older feature layout are not treated as compatible and will be replaced lazily when the current labeled dataset is prepared for a new analysis.

Category/game context is a conservative calibration layer on top of the global personal probability. It requires at least 20 category labels, at least 5 Keep + 5 Reject, and at least 2 source VODs. Blank/`Unsorted` content falls back to the global learner.

Mining-profile context is handled differently: the **numeric effective weights** are model features, while the profile name is retained as provenance/statistics rather than a direct categorical bonus. This avoids teaching the model a shortcut such as “Reaction-heavy always means Keep.”

If learner preparation or prediction errors, analysis fails open to the original heuristic ranking.

See `LEARNING.md` for the full model/activation contract.

Current dataset counts are available with:

```powershell
HighlightMiner.exe learning-stats
```

## Export behavior

Exports never silently replace an existing same-named clip. The next available suffix is selected instead:

```text
H003_clutch.mp4
H003_clutch_2.mp4
H003_clutch_3.mp4
```

Each export is recorded in SQLite.
