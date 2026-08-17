# Same-VOD reruns and learning data

`v0.2-dev` separates a physical VOD (**source**) from each **analysis run**. Re-analyzing the same source creates a new run instead of overwriting history.

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

CLI full-reprocess equivalent:

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --no-reuse
```

## Learning-ready review data

The review states map to future supervised learning as follows:

| State | Label |
|---|---:|
| Keep | `1` positive |
| Reject | `0` negative |
| Unreviewed | `None` / unlabeled |

**Unreviewed is not treated as Reject.** Not having judged a candidate is not negative preference evidence.

Candidate rows retain the original heuristic rank/score, audio/transcript/chat scores, combined-signal statistics, active-signal count, candidate duration, chat availability, scoring weights, content/game label, source/run IDs, algorithm version, and feature-schema version.

The review layer also retains user-adjusted timing, title edits, review timestamps, meaningful review changes in `review_events`, and every export in `exports`. This preserves stronger behavioral signals for later experimentation without retraining Whisper.

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

## Current status

The **dataset plumbing is implemented; the preference learner itself is not**. The first learner should train on explicit Keep/Reject examples only. Unreviewed data remains available for statistics/calibration, and repeated runs of the same source should be deduplicated or grouped during training so reruns do not accidentally overweight one VOD.
