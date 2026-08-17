# ⛏️ HighlightMiner v0.2-dev

**Experimental local-first VOD highlight detection with SQLite history, same-VOD reruns, a native Windows desktop shell, and future preference learning in mind.**

> **Development branch:** `v0.2-dev` — reports version `0.2.0.dev0`
>
> Stable/simple v0.1.x remains on [`main`](https://github.com/jekku0966/HighlightMiner/tree/main).

HighlightMiner analyzes long VODs using audio excitement, local Whisper transcription, reaction-heavy speech cues, and optional chat bursts, then presents ranked candidate moments for human review.

## Windows desktop UI

On Windows, Streamlit remains the UI engine but is hosted inside a native **HighlightMiner** window using pywebview + Microsoft Edge WebView2. Double-clicking `HighlightMiner.exe` no longer opens a normal browser tab.

```text
HighlightMiner.exe
        │
        ├── Streamlit backend on 127.0.0.1:8501
        │
        └── pywebview / WebView2 window
                    │
                    ▼
            HighlightMiner UI
```

Closing the window shuts down the local Streamlit child process. The in-app **Exit HighlightMiner** button does the same thing.

Browser fallback remains available:

```powershell
HighlightMiner.exe ui --browser
```

## SQLite instead of JSON state

Generated structured state lives in one local database:

```text
HighlightMiner/
├── HighlightMiner.exe
├── settings.json
├── highlightminer.db
└── highlightminer_work/
    ├── .previews/
    └── clips/
```

`settings.json` intentionally stays human-editable. The database stores analyses, candidates, transcript/audio/chat features, review state, timing/title edits, source/run history, review events, and exports.

New v0.2 analyses no longer need durable copies of:

```text
analysis.json
review.json
transcript.json
transcript_meta.json
audio_features.json
chat_features.json
```

The temporary 16 kHz analysis WAV is deleted after useful data is committed.

## Same VOD, multiple runs

v0.2 distinguishes the physical **source VOD** from an **analysis run**:

```text
source VOD
├── run 1
├── run 2
└── run 3
```

A sampled content fingerprint recognizes a byte-identical VOD without relying on filename/path. When the selected VOD already has history, the UI offers:

- **Load latest** — reopen the newest run;
- **Analyze again** — create a new run while reusing compatible upstream work;
- **Force full reprocess** — create a new run and ignore cached stages.

Candidate ranking always runs again. Compatible audio features, Whisper transcript, and chat features are reused independently. Changing only ranking settings can therefore turn a long rerun into a quick rerank instead of another full transcription pass.

`reaction_phrases` do not invalidate the Whisper transcript; cached transcript text is simply rescored.

CLI full-reprocess equivalent:

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --no-reuse
```

Detailed behavior: [`RERUNS_AND_LEARNING.md`](RERUNS_AND_LEARNING.md).

## Learning-ready review history

v0.2 preserves explicit review semantics for the future preference learner:

| Review state | Future label |
|---|---:|
| Keep | `1` positive |
| Reject | `0` negative |
| Unreviewed | `None` / unlabeled |

**Unreviewed is not a Reject.** It means the user has not supplied a preference label yet.

Each candidate stores its original heuristic rank/score plus a feature snapshot containing signal scores and useful ranking context. The database also retains review-state changes, timing/title edits, export history, source/run IDs, content/game labels, and algorithm/feature-schema versions.

Dataset status can be inspected with:

```powershell
HighlightMiner.exe learning-stats
```

The data plumbing is implemented. **The actual personal preference learner/reranker is not implemented yet.**

## Review/export flow

The development sidebar provides local VOD/chat/settings/work-folder pickers, Content/Game, Analyze VOD, source-aware Analysis history, v0.1 import, and learning-data counts.

The main area provides ranked candidates, a lightweight preview clip, timing controls, Keep/Reject/Unreview, title edits, signal/transcript information, and export.

Exports use category subfolders such as:

```text
clips/
└── Overwatch 2/
    ├── H003_clutch.mp4
    └── H003_clutch_2.mp4
```

Existing clips are never silently overwritten; a numbered suffix is chosen and each export is recorded in SQLite.

## Legacy v0.1 import

The sidebar includes **Import v0.1 analysis.json**. Select the old `analysis.json`; when companion files are present, HighlightMiner also migrates review state, transcript, audio features, and chat features into `highlightminer.db`.

The referenced source VOD must still exist locally.

## Analysis pipeline

```text
VOD + optional chat
        │
        ├── source identity / previous-run lookup
        │
        ├── FFmpeg analysis audio ─────────────┐
        ├── audio features                     │ reusable when compatible
        ├── faster-whisper transcript           │
        └── chat features ─────────────────────┘
                    │
                    ▼
              signal fusion
                    │
                    ▼
             candidate ranking
                    │
                    ▼
               SQLite run
                    │
                    ▼
          review / export / history
```

## Security posture

The development branch includes local-file validation, UNC/network-path rejection for source media, chat/settings size and extension limits, JSON nesting limits, numeric settings validation, a standard Whisper-model allow-list, loopback-only Streamlit, forced WebView2 desktop rendering, immutable GitHub Actions revisions, and SHA-256 checksums for Windows release ZIPs.

The sampled VOD fingerprint is for **same-source identity**, not security/integrity verification. See [`SECURITY.md`](SECURITY.md).

## Recommended Twitch workflow

Use [TwitchDownloader](https://github.com/lay295/TwitchDownloader) to obtain a matching VOD and JSON chat export:

```text
TwitchDownloader
├── stream.mp4
└── stream_chat.json
        │
        ▼
   HighlightMiner
```

TwitchDownloader is not bundled or invoked automatically.

## Requirements

- Python **3.10+** for source mode
- FFmpeg + ffprobe
- Windows x64 for the current packaged target
- Microsoft Edge **WebView2 Runtime** for the native window
- NVIDIA GPU optional but useful for larger Whisper models

See [`BUILD_WINDOWS.md`](BUILD_WINDOWS.md) and [`CUDA_SETUP.md`](CUDA_SETUP.md) for packaging/runtime setup.

## Running from source

```powershell
git clone https://github.com/jekku0966/HighlightMiner.git
cd HighlightMiner
git switch v0.2-dev
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.bat
```

Environment check:

```powershell
.\.venv\Scripts\python.exe -m highlightminer doctor
```

## CLI examples

Analyze:

```powershell
.\.venv\Scripts\python.exe -m highlightminer analyze "D:\VODs\stream.mp4" `
  --chat "D:\VODs\stream_chat.json" `
  --content "Overwatch 2"
```

Force fresh processing:

```powershell
.\.venv\Scripts\python.exe -m highlightminer analyze "D:\VODs\stream.mp4" --no-reuse
```

Other commands:

```powershell
.\.venv\Scripts\python.exe -m highlightminer ui
.\.venv\Scripts\python.exe -m highlightminer ui --browser
.\.venv\Scripts\python.exe -m highlightminer history
.\.venv\Scripts\python.exe -m highlightminer learning-stats
.\.venv\Scripts\python.exe -m highlightminer import-legacy "D:\old-run\analysis.json"
.\.venv\Scripts\python.exe -m highlightminer export <analysis-id>
```

Use `--help` as the source of truth while the dev CLI evolves.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

The Windows CI also validates PyInstaller, frozen CTranslate2/faster-whisper imports, the pywebview/WebView2 backend, the packaged Streamlit localhost server, ZIP generation, and checksums.

Before v0.2 replaces v0.1.x, it still needs real-machine validation of migration, a fresh SQLite analysis, same-VOD cached reruns, force-full-reprocess, multi-run review/export persistence, and the eventual preference learner.

## Documentation

- [`V0.2_DEV.md`](V0.2_DEV.md) — architecture/status
- [`RERUNS_AND_LEARNING.md`](RERUNS_AND_LEARNING.md) — rerun/cache/learning contract
- [`BUILD_WINDOWS.md`](BUILD_WINDOWS.md) — Windows build/package notes
- [`CUDA_SETUP.md`](CUDA_SETUP.md) — CUDA/CTranslate2 setup
- [`SECURITY.md`](SECURITY.md) — threat model/security notes
- [`CHANGELOG.md`](CHANGELOG.md) — project changes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contribution guidelines
- [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md) — dependencies/provenance

## Provenance and license

HighlightMiner uses faster-whisper, CTranslate2, FFmpeg, Streamlit, pywebview, Microsoft Edge WebView2, and optionally TwitchDownloader as a companion input tool. See [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md).

The project has been developed with AI coding assistance from OpenAI's ChatGPT and should be reviewed/tested like any human-authored code.

HighlightMiner's own source is **MIT licensed**. Third-party dependencies/models retain their own licenses.
