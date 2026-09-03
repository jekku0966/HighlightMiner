# ⛏️ HighlightMiner v0.1 — Legacy MVP

> **Status:** Legacy / proof of concept. This branch contains the original crude MVP that proved the HighlightMiner workflow was viable. The current actively maintained version is [`v0.2-dev`](https://github.com/jekku0966/HighlightMiner/tree/v0.2-dev).

**TL;DR:** HighlightMiner scans long VODs using audio activity, local Whisper speech cues, and optional chat activity to surface moments worth reviewing. You review, retime, keep or reject those candidates and export clips locally — it finds the interesting bits, but the human still decides what is actually worth clipping.

## What v0.1 is

v0.1 is the original working MVP of HighlightMiner. It is intentionally simple, folder-driven, and rough around the edges; it exists primarily as the project's first functional proof of concept and as a reference for how the project evolved.

If you want the version currently being developed and tested, use [`v0.2-dev`](https://github.com/jekku0966/HighlightMiner/tree/v0.2-dev).

## What it does

```text
VOD + optional chat
        │
        ├── FFmpeg audio extraction
        ├── faster-whisper transcription
        ├── audio excitement / onset scan
        └── chat velocity / burst scan
                    │
                    ▼
              signal fusion
                    │
                    ▼
          ranked candidate moments
                    │
                    ▼
          local Streamlit review UI
                    │
          Keep / Reject / retime
                    │
                    ▼
              FFmpeg export
```

HighlightMiner is a **candidate finder**, not a finished-video editor and not an automatic comedy oracle. It tells you where to look first; you make the final call.

## v0.1 workflow

The v0.1 interface works directly with local files and folders:

1. Choose a VOD.
2. Optionally provide a matching chat export.
3. Choose a work folder and settings file.
4. Run **Analyze VOD**.
5. Review the ranked candidate moments.
6. Keep, Reject, Unreview, retime, or title candidates.
7. Export kept clips locally with FFmpeg.

Analysis and review state is stored in generated files such as `analysis.json` and `review.json`.

## Main features

- **Local-first processing** — VODs stay on disk; no cloud API is required for the normal v0.1 workflow.
- **Local Whisper transcription** — `faster-whisper`/CTranslate2 can use CUDA when available and fall back to CPU.
- **Audio scoring** — detects bursts of audio activity/excitement.
- **Reaction-phrase scoring** — transcript cues can strengthen likely highlight moments.
- **Optional chat scoring** — JSON, JSONL/NDJSON, and CSV chat exports are supported.
- **Signal fusion** — audio, transcript, and chat cues contribute to one ranked candidate list.
- **Human review** — Keep, Reject, Unreview, adjust timing, and title clips.
- **Local export** — FFmpeg renders the final kept clips.

## Recommended Twitch input workflow

For Twitch testing, [TwitchDownloader](https://github.com/lay295/TwitchDownloader) can be used to obtain the VOD and matching JSON chat export:

```text
TwitchDownloader
├── stream.mp4
└── stream_chat.json
        │
        ▼
   HighlightMiner
```

TwitchDownloader is not bundled with or automatically invoked by HighlightMiner.

## Requirements

- Python **3.10+**
- FFmpeg + ffprobe
- NVIDIA GPU optional but useful for larger Whisper models
- Windows convenience scripts are included; the Python project itself is not intentionally Windows-only

Detailed setup docs:

- [`BUILD_WINDOWS.md`](BUILD_WINDOWS.md)
- [`CUDA_SETUP.md`](CUDA_SETUP.md)

## Quick start — Windows

### 1. Clone

```powershell
git clone https://github.com/jekku0966/HighlightMiner.git
cd HighlightMiner
```

`main` contains the legacy v0.1 MVP.

### 2. Provide FFmpeg

Put matching `ffmpeg` and `ffprobe` executables in either:

```text
HighlightMiner/bin/
```

or the project root, or install them on the system `PATH`.

### 3. Install

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

### 4. Check the environment

```powershell
.\.venv\Scripts\python.exe -m highlightminer doctor
```

### 5. Launch

```powershell
.\run.bat
```

## CLI

Analyze a VOD:

```powershell
.\.venv\Scripts\python.exe -m highlightminer analyze "D:\VODs\stream.mp4" --work-dir ".\highlightminer_work\stream-001"
```

Analyze with chat:

```powershell
.\.venv\Scripts\python.exe -m highlightminer analyze "D:\VODs\stream.mp4" `
  --chat "D:\VODs\stream_chat.json" `
  --work-dir ".\highlightminer_work\stream-001"
```

Launch the UI:

```powershell
.\.venv\Scripts\python.exe -m highlightminer ui
```

Export clips marked **Keep**:

```powershell
.\.venv\Scripts\python.exe -m highlightminer export ".\highlightminer_work\stream-001\analysis.json"
```

## v0.1 work directory

```text
highlightminer_work/stream-001/
├── analysis_audio.wav
├── audio_features.json
├── transcript.json
├── transcript_meta.json
├── chat_features.json       # when chat is supplied
├── analysis.json
├── review.json
└── clips/
```

The expensive transcription/features can be reused when reopening an existing analysis.

## Chat input

Supported containers:

- JSON
- JSONL / NDJSON
- CSV

Minimal CSV:

```csv
timestamp,message
12.4,LUL
12.8,WHAT
13.0,NO WAY
```

## Tuning

Edit `settings.json`.

| Setting | Purpose |
|---|---|
| `whisper_model` | Whisper model used for transcription |
| `device` | `auto`, `cuda`, or `cpu` |
| `compute_type` | CTranslate2 compute type |
| `language` | Force a language or use automatic detection |
| `pre_roll_sec` | Context before a detected moment |
| `post_roll_sec` | Context after a detected moment |
| `merge_gap_sec` | Merge nearby spikes into one candidate |
| `max_candidate_sec` | Maximum suggested clip duration |
| `min_candidate_score` | Main candidate threshold |
| `max_candidates` | Review-queue cap |
| `weights` | Relative audio/transcript/chat contribution |
| `reaction_phrases` | User-configurable reaction phrases |

## Current version — v0.2

The active HighlightMiner version lives on [`v0.2-dev`](https://github.com/jekku0966/HighlightMiner/tree/v0.2-dev).

Compared with this MVP, v0.2 adds a native Windows shell, SQLite-backed state and analysis history, same-VOD reruns with reusable expensive analysis data, in-app settings and model-access controls, stronger review/export handling, better diagnostics, and infrastructure for future preference learning.

See [`V0.2_DEV.md`](https://github.com/jekku0966/HighlightMiner/blob/v0.2-dev/V0.2_DEV.md) for the current architecture and status.

## v0.1 limitations

This MVP does **not** currently:

- understand gameplay visually;
- know whether a joke or moment is actually good;
- automatically learn your taste;
- download Twitch/YouTube VODs itself;
- publish clips to social platforms;
- function as a full video editor.

Treat the ranking as **"where should I look first?"**, not **"the machine has finished my edit."**

## Provenance and dependencies

HighlightMiner uses documented public interfaces from projects including:

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [CTranslate2](https://github.com/OpenNMT/CTranslate2)
- [FFmpeg](https://ffmpeg.org/)
- [Streamlit](https://streamlit.io/)
- [TwitchDownloader](https://github.com/lay295/TwitchDownloader) as a recommended input companion, not a runtime dependency

The project was developed with AI coding assistance from OpenAI's ChatGPT. See [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md) for the detailed provenance policy.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

## Documentation

- [`BUILD_WINDOWS.md`](BUILD_WINDOWS.md) — Windows packaging/build notes
- [`CUDA_SETUP.md`](CUDA_SETUP.md) — CUDA/CTranslate2 setup
- [`CHANGELOG.md`](CHANGELOG.md) — project changes
- [`RELEASE_NOTES_v0.1.2.md`](RELEASE_NOTES_v0.1.2.md) — v0.1 release notes
- [`SECURITY.md`](SECURITY.md) — security notes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contribution guidelines
- [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md) — dependencies and provenance

## License

HighlightMiner's own source code is released under the **MIT License**. Third-party software, models, and dependencies retain their own licenses.
