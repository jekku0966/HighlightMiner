# ⛏️ HighlightMiner v0.2-learning

**Experimental local-first VOD highlight detection with SQLite history, same-VOD reruns, in-app settings, a native Windows shell, and conservative personal preference reranking.**

> Experimental learning branch: `v0.2-learning` — version `0.2.0.dev0`  
> Integration base: `v0.2-dev`  
> Stable/simple v0.1.x remains on `main`.

HighlightMiner analyzes long VODs using audio excitement, local Whisper transcription, reaction-heavy speech cues, and optional chat bursts, then presents ranked candidate moments for human review.

## Windows desktop UI

On Windows, Streamlit is hosted inside a native HighlightMiner window using pywebview + Microsoft Edge WebView2. Double-clicking `HighlightMiner.exe` does not need to open a normal browser tab. Closing the native window or using **Exit HighlightMiner** shuts down the local Streamlit process.

Browser fallback remains available:

```powershell
HighlightMiner.exe ui --browser
```

## Official Windows binaries

Ordinary GitHub Actions runs build and smoke-test the frozen Windows application for regression coverage, but they do **not** publish a downloadable EXE or ZIP artifact.

Official HighlightMiner Windows binaries are only the assets manually attached by the maintainer to the repository's **GitHub Releases** page. Official releases include a versioned Windows ZIP, `SHA256SUMS.txt`, and `RELEASE_MANIFEST.json`; GitHub provides source-code ZIP/tar.gz archives automatically from the release tag.

Because HighlightMiner is open source, third parties can still build their own executables from the public source. Those builds are not official HighlightMiner binaries unless they are published as release assets by the maintainer.

## SQLite-backed application state

v0.2 keeps structured state in `highlightminer.db`: analyses, candidates, transcript/audio/chat features, source/run history, Keep/Reject/Unreviewed reviews, timing/title edits, review events, export history, active desktop-app settings, and experimental preference models.

```text
HighlightMiner/
├── HighlightMiner.exe
├── highlightminer.db
├── settings.json        # migration/default/interchange file; not normal UI state
└── highlightminer_work/
    ├── .previews/
    └── clips/
```

New analyses no longer need durable `analysis.json`, `review.json`, `transcript.json`, `audio_features.json`, or `chat_features.json` files. The temporary 16 kHz analysis WAV is deleted after useful data is committed.

## In-app Settings page

Use **⚙️ Settings** in the sidebar instead of hand-editing JSON. The page provides:

- Whisper model/device/compute/language/beam/VAD controls;
- explicit recognition-model download permission and local-model selection;
- candidate threshold/count and clip timing controls;
- audio analysis window/hop controls;
- `0.00–1.00` Audio / Transcript / Chat weight sliders with effective normalized percentages;
- editable reaction phrases;
- **Save settings**, **Reset defaults**, **Import settings**, and **Export settings**.

HighlightMiner never silently opts the user into downloading a speech-recognition model. A fresh database asks **Allow model downloads** or **No model downloads**. The decision is stored locally in SQLite and can be changed later. Users can also point HighlightMiner at a manually downloaded local CTranslate2 Whisper model folder; local model selection works without granting download permission. Imported settings files cannot grant model-download consent.

Signal presets are **Balanced**, **Reaction-heavy**, **Chat-heavy**, and **Audio-heavy**. Presets alter weights only; they never secretly change Whisper, thresholds, or clip timing. Manual weighting becomes **Custom**. If chat is absent, its weight becomes zero and audio/transcript are renormalized automatically.

On the first database-backed settings load, HighlightMiner imports the local/package `settings.json` once so existing defaults/reaction phrases survive migration. SQLite is authoritative after that. JSON remains available for backup, sharing, and explicit import/export.

Saved changes affect future analyses/reruns only. Every existing analysis retains its original settings snapshot.

See `SETTINGS.md` for the complete settings contract.

## Same VOD, multiple runs

v0.2 separates a physical source VOD from its analysis runs:

```text
source VOD
├── run 1
├── run 2
└── run 3
```

A sampled content fingerprint recognizes a byte-identical VOD without relying on filename/path. When a VOD already has history, the UI offers **Load latest**, **Analyze again**, and **Force full reprocess**.

Candidate ranking always runs again. Compatible audio features, Whisper transcript, and chat features are reused independently. Changing only scoring settings can therefore reduce a rerun to a quick rerank. Changing reaction phrases reuses compatible Whisper text and rescoring does not require retranscription.

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --no-reuse
```

See `RERUNS_AND_LEARNING.md` for source identity/cache rules.

## Personal preference learning

Review semantics remain explicit:

| State | Learning label |
|---|---:|
| Keep | `1` positive |
| Reject | `0` negative |
| Unreviewed | unlabeled |

The heuristic detector still creates the candidate pool and its base score is never overwritten. The learner is a conservative NumPy logistic-regression reranker: it starts only after 30 labeled candidates, at least 8 examples of each class, and labels from at least 3 source VODs. Its influence begins at 10% and is capped at 35%, so the heuristic always remains the majority of the final score.

### Category / game context

`Content / Game` is learning context. The global model works everywhere; category-specific calibration only activates after a category has at least 20 labels, at least 5 Keep + 5 Reject, and at least 2 source VODs. `Unsorted` stays on the global model.

### Mining-profile context

Every new run records the mining profile (`Balanced`, `Reaction-heavy`, `Chat-heavy`, `Audio-heavy`, or `Custom`). The learner uses the actual normalized Audio / Transcript / Chat weights as numeric model inputs and keeps the profile name as provenance/diagnostics. It does not give a blind categorical bonus to a preset name.

The review UI can show Base / Personal / Final ranking scores, current learner influence, active category context, and mining-profile coverage. Learner failures fail open to the base heuristic ranking.

```powershell
HighlightMiner.exe learning-stats
```

See `LEARNING.md` for the model, activation gates, category/profile rules, and stored ranking provenance.

## Review and export

The Mine / Review page provides local VOD/chat/work-folder pickers, Content/Game, source-aware history, v0.1 import, candidate previews, Keep/Reject/Unreview, timing/title editing, transcript/signal context, and export.

Exports use sanitized category folders and never silently overwrite an existing file:

```text
clips/
└── Overwatch 2/
    ├── H003_clutch.mp4
    └── H003_clutch_2.mp4
```

## Legacy v0.1 import

Use **Import v0.1 analysis.json** in the sidebar. HighlightMiner migrates the analysis and, when present, companion review/transcript/audio/chat data into SQLite. The referenced source VOD must still exist locally.

## Security posture

The dev branches include local-file validation, automatic UNC/network-source rejection, chat/settings size limits, JSON nesting limits, numeric settings validation, standard Whisper-model allow-listing with explicit custom-model opt-in, explicit model-download consent, local-only manual model selection, loopback-only Streamlit, forced WebView2 rendering, pinned GitHub Actions, validation-only public Windows CI, and SHA-256/manifest provenance for official release assets.

The sampled VOD fingerprint is for source identity, not security/integrity verification. See `SECURITY.md`.

## Requirements

- Python 3.10+ for source mode
- FFmpeg + ffprobe
- Windows x64 for the current packaged target
- Microsoft Edge WebView2 Runtime for the native window
- NVIDIA GPU optional but useful for larger Whisper models

For Twitch VOD/chat acquisition, TwitchDownloader is the recommended companion tool; it is not bundled or invoked automatically.

## Running from source

```powershell
git clone https://github.com/jekku0966/HighlightMiner.git
cd HighlightMiner
git switch v0.2-learning
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.bat
```

Tests:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

## Documentation

- `LEARNING.md` — experimental preference model, category/profile context, activation gates
- `SETTINGS.md` — in-app settings, presets, import/export
- `V0.2_DEV.md` — v0.2 base architecture/status
- `RERUNS_AND_LEARNING.md` — rerun/cache/learning-data contract
- `BUILD_WINDOWS.md` — Windows build/package notes
- `CUDA_SETUP.md` — CUDA/CTranslate2 setup
- `SECURITY.md` — threat model/security notes
- `CHANGELOG.md` — project changes
- `ATTRIBUTIONS.md` — dependency/provenance notes

HighlightMiner's own source is MIT licensed. Third-party dependencies/models retain their own licenses. The project has been developed with AI coding assistance and should be reviewed/tested like any human-authored code.
