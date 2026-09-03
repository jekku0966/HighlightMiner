# ⛏️ HighlightMiner v0.2

> **Status:** Current actively maintained version. Development and testing happen on `v0.2-dev`. v0.1 on `main` is the original crude MVP / proof of concept and is kept mainly for history and reference.

**TL;DR:** HighlightMiner scans long VODs and ranks moments that are likely worth reviewing using audio activity, optional local Whisper speech cues, and optional chat activity. You decide what is worth keeping, adjust the timing if needed, and export the clips locally.

## What HighlightMiner does

```text
VOD + optional chat
        │
        ├── audio analysis
        ├── optional local Whisper transcription
        ├── reaction-phrase scoring
        └── optional chat-burst scoring
                    │
                    ▼
              signal fusion
                    │
                    ▼
          ranked candidate moments
                    │
                    ▼
             human review
          Keep / Reject / retime
                    │
                    ▼
              FFmpeg export
```

The goal is simple: turn hours of VOD into a much smaller ranked list of moments that are actually worth checking.

HighlightMiner keeps the human in control. It suggests where to look first. You decide what is good, fix the clip boundaries, name it, and choose whether it gets exported.

It is not a full video editor and it does not try to make the creative decision for you.

## v0.2 at a glance

Compared with the original v0.1 MVP, v0.2 is the current application architecture. It adds:

- a native Windows desktop shell around the local Streamlit UI;
- SQLite-backed analyses, review state, settings, history, and export data;
- same-VOD reruns with reusable analysis data;
- in-app analysis settings and model controls;
- explicit local-model, model-download, and no-transcription choices;
- persistent Keep / Reject / Unreviewed decisions;
- editable clip timing and titles;
- a persistent export queue and export history;
- analysis deletion with an impact preview and explicit confirmation;
- better diagnostics, timing, cancellation, and shutdown behavior;
- data plumbing for future preference learning while keeping the user in control.

v0.2 is still under active testing, so bugs and rough edges are possible. The `-dev` branch name is there for a reason, but this is the version that represents HighlightMiner today.

## Windows desktop UI

On Windows, Streamlit runs inside a native HighlightMiner window using pywebview and Microsoft Edge WebView2. Running `HighlightMiner.exe` opens the application directly instead of requiring a normal browser tab.

Browser fallback is still available:

```powershell
HighlightMiner.exe ui --browser
```

Closing the native window or using **Exit HighlightMiner** shuts down the local Streamlit process when it is safe to do so. Active non-cancellable analysis or export stages keep shutdown locked until they reach a safe state.

## Local-first processing

HighlightMiner is designed around local media processing:

- source VODs are read from disk;
- FFmpeg handles media extraction and export;
- Whisper runs locally through `faster-whisper`/CTranslate2 when speech recognition is enabled;
- analysis and review state is stored locally in SQLite;
- no cloud inference API is required for the normal workflow.

For Twitch VOD and chat acquisition, [TwitchDownloader](https://github.com/lay295/TwitchDownloader) is the recommended companion tool. It is not bundled with HighlightMiner and HighlightMiner does not launch it automatically.

## SQLite-backed application state

v0.2 stores structured state in `highlightminer.db`, including:

- source VOD identity and run history;
- analyses and ranked candidates;
- transcript, audio, and chat features;
- Keep / Reject / Unreviewed reviews;
- timing and title edits;
- review events;
- persistent export queue and export history;
- the active desktop-app settings profile.

```text
HighlightMiner/
├── HighlightMiner.exe
├── highlightminer.db
├── settings.json        # migration/default/interchange file
└── highlightminer_work/
    ├── .previews/
    └── clips/
```

Completed analyses are kept as history entries. A selected analysis can only be permanently deleted after an impact preview and explicit confirmation. Other runs stay untouched, source run numbers are not reused, and already exported video files are not silently deleted from disk.

## Same VOD, multiple runs

v0.2 separates the physical source VOD from its analysis runs:

```text
source VOD
├── run 1
├── run 2
└── run 3
```

A sampled content fingerprint recognizes a byte-identical VOD without relying only on its filename or path.

When HighlightMiner recognizes a VOD with existing history, the UI can offer:

- **Load latest:** Reopen the latest existing analysis.
- **Analyze again:** Create a new run while reusing compatible analysis data.
- **Force full reprocess:** Rebuild the analysis from scratch.

Candidate ranking always runs again. Compatible audio features, Whisper transcript, and chat features can be reused independently, so changing only scoring settings can avoid unnecessary retranscription.

## Speech recognition and model access

Whisper transcription is optional.

HighlightMiner does not silently opt the user into downloading a speech-recognition model. When a new analysis needs transcription, it can use:

1. a manually selected local CTranslate2 Whisper model;
2. an already cached supported model;
3. an explicitly approved model download;
4. **Continue without speech**, which finishes the analysis using the signals that are still available.

The preference can be changed later under **Settings → Analysis engine → Model access**.

Imported settings cannot silently grant model-download permission.

The CLI is intentionally non-interactive for model consent. If a model is missing, choose explicitly:

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --allow-model-download
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --no-transcription
```

These per-command flags do not silently rewrite the normal desktop preference.

## In-app settings

Use **⚙️ Settings** in the sidebar instead of manually editing JSON for normal use.

Current controls include:

- Whisper model, device, compute type, language, beam, and VAD options;
- model-download permission and local-model selection;
- candidate threshold/count and clip timing controls;
- audio analysis window/hop controls;
- Audio / Transcript / Chat weighting;
- editable reaction phrases;
- settings reset, import, and export.

Signal presets include **Balanced**, **Reaction-heavy**, **Chat-heavy**, and **Audio-heavy**. Unavailable signals get zero effective weight and the remaining available signals are renormalized automatically.

Saved settings affect future analyses and reruns. Existing analyses keep their original settings snapshot.

See [`SETTINGS.md`](SETTINGS.md) for the complete settings contract.

## Review and export

The Mine / Review workflow includes:

- local VOD, chat, and work-folder selection;
- content/game labeling;
- source-aware analysis history;
- v0.1 import;
- ranked candidate review;
- local preview;
- Keep / Reject / Unreviewed state;
- timing and title editing;
- transcript and signal context;
- a persistent export queue.

Kept clips can be staged before FFmpeg starts. Queue entries survive Streamlit reruns, reject duplicates, show per-item and overall status, retain failures for retry, and record successful outputs in export history.

A custom clip title becomes the clean filename. Untitled clips fall back to the candidate ID.

Exports use sanitized category folders and do not silently overwrite an existing file:

```text
clips/
└── Overwatch 2/
    ├── clutch.mp4
    └── clutch_2.mp4
```

## Learning-ready review history

Review states are explicit:

| Review state | Future label |
|---|---:|
| Keep | `1` positive |
| Reject | `0` negative |
| Unreviewed | unlabeled |

Unreviewed is **not** silently treated as Reject.

Candidate feature snapshots, ranking scores, content/game labels, source/run IDs, settings snapshots, review changes, timing edits, titles, exports, signal availability, and effective scoring weights are kept so future preference-learning experiments have usable data.

```powershell
HighlightMiner.exe learning-stats
```

The data plumbing exists. A personal preference learner is **not** part of the current v0.2 behavior, and human decisions remain authoritative.

## Legacy v0.1 import

v0.2 can import an old v0.1 `analysis.json` and, when available, its companion review, transcript, audio, and chat data into SQLite. The referenced source VOD must still exist locally.

The v0.1 branch remains available on [`main`](https://github.com/jekku0966/HighlightMiner/tree/main), but it should be treated as the legacy MVP rather than the current HighlightMiner experience.

## Requirements

- Python **3.10+** for source mode
- FFmpeg + ffprobe
- Windows x64 for the current packaged target
- Microsoft Edge WebView2 Runtime for the native window
- NVIDIA GPU optional but useful for larger Whisper models

## Running from source

```powershell
git clone https://github.com/jekku0966/HighlightMiner.git
cd HighlightMiner
git switch v0.2-dev
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.bat
```

Run the tests with:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

## Official Windows binaries

Normal GitHub Actions runs can build and smoke-test the frozen Windows application for regression coverage, but they do **not** automatically make every CI build an official downloadable release.

Official Windows binaries are the assets published by the maintainer on the repository's **GitHub Releases** page. Release packages can include the versioned Windows ZIP, `SHA256SUMS.txt`, and `RELEASE_MANIFEST.json` alongside GitHub's automatically generated source archives.

Third parties can build the open-source application themselves, but those builds are not official HighlightMiner binaries unless the maintainer publishes them as release assets.

## Security posture

v0.2 includes local-file validation, UNC/network-source rejection, chat/settings size limits, JSON nesting limits, numeric settings validation, standard Whisper-model allow-listing with explicit custom-model opt-in, just-in-time model-download consent, loopback-only Streamlit, forced WebView2 rendering, pinned GitHub Actions, and release checksum/manifest support.

The sampled VOD fingerprint is used for source identity, not cryptographic integrity verification.

See [`SECURITY.md`](SECURITY.md) for details.

## Current limitations

HighlightMiner does **not** currently:

- understand gameplay visually;
- know whether a joke or moment is actually good;
- automatically produce a finished edited video;
- replace the human review step;
- automatically learn and override your taste;
- download Twitch/YouTube VODs itself;
- publish clips directly to social platforms.

Treat the ranking as **"where should I look first?"**, not **"the edit is finished."**

## Documentation

- [`SETTINGS.md`](SETTINGS.md): settings, model access, presets, import/export
- [`V0.2_DEV.md`](V0.2_DEV.md): architecture and current development status
- [`RERUNS_AND_LEARNING.md`](RERUNS_AND_LEARNING.md): source identity, cache, rerun, and learning contract
- [`BUILD_WINDOWS.md`](BUILD_WINDOWS.md): Windows build/package notes
- [`CUDA_SETUP.md`](CUDA_SETUP.md): CUDA/CTranslate2 setup
- [`SECURITY.md`](SECURITY.md): threat model and security notes
- [`CHANGELOG.md`](CHANGELOG.md): project changes
- [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md): dependency and provenance notes

## Provenance and license

HighlightMiner uses projects including `faster-whisper`, CTranslate2, FFmpeg, Streamlit, pywebview, and Microsoft Edge WebView2 through their documented interfaces. TwitchDownloader is a recommended input companion rather than a runtime dependency.

The project has been developed with AI coding assistance from OpenAI's ChatGPT and should be reviewed and tested like any human-authored code. See [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md) for provenance details.

HighlightMiner's own source code is released under the **MIT License**. Third-party software, models, and dependencies retain their own licenses.
