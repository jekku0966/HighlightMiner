# HighlightMiner settings

`v0.2` manages normal user settings inside the application. The active profile is stored in `highlightminer.db`; users no longer need to edit `settings.json` for normal use.

## Settings page

Open **⚙️ Settings** from the HighlightMiner sidebar. The page is split into:

- **Analysis engine** — model access/download permission, local model folder, Whisper model, device, compute type, language, beam size, and VAD;
- **Detection & weights** — candidate threshold/count, clip timing, audio analysis windows, and signal weighting;
- **Reaction phrases** — one phrase per line;
- **Import / Export** — migrate, back up, or share a JSON settings profile.

Press **Save settings** to make the normal editor state active. Saved changes apply to future analysis runs and reruns. Existing analyses retain the exact settings snapshot they were created with.

VOD, chat, Content / Game, and work-folder selections on the Mine page are kept when you visit Settings and return. Settings widgets are rehydrated from the saved SQLite profile if Streamlit recreated them, so navigating between pages does not replace saved values with widget defaults.

While a VOD analysis is actively processing, the Settings navigation is locked. HighlightMiner queues the analysis first, rerenders the UI with Settings disabled, and only then starts the long-running work. Settings unlocks after completion, an error, or when the analysis pauses for an explicit model decision.

## Recognition-model downloads and local models

HighlightMiner does not silently opt a user into recognition-model downloads. A fresh database starts at **Ask before any download**, but this does not interrupt application startup.

When an analysis actually needs a fresh Whisper transcript, HighlightMiner checks in this order:

1. a manually selected local CTranslate2 Whisper model;
2. an already downloaded model in the local Hugging Face cache, checked without networking;
3. the saved model-download permission.

If neither a local nor cached model is available and permission is still **Ask**, the Mine page offers three explicit choices:

- **Download model** — allow the selected faster-whisper model to download from Hugging Face and remember **Allow model downloads**;
- **Choose local model** — select and validate a compatible local model folder without granting download permission;
- **Continue without speech** — remember **Never download models** and finish the analysis using audio plus optional chat.

If **Never download models** was already saved, a missing model does not stop HighlightMiner. Fresh analyses continue without transcription unless a local/cached model is available. The choice can be changed later under **Settings → Analysis engine → Model access**. It is deliberately separate from imported/exported JSON settings, so importing a profile cannot grant network-download permission on the user's behalf.

A reusable transcript from an earlier compatible run is used before any model decision is needed. In other words, a rerun that can reuse Whisper text does not prompt merely because the model itself is currently absent.

HighlightMiner automatically creates a local `models` directory beside the application/source root. This directory is only a convenient place for **manually obtained models**, so it is completely normal for it to be empty. Models downloaded by faster-whisper/Hugging Face are stored in the Hugging Face Hub cache instead; the Settings page displays the resolved cache location separately.

A user can place a manually obtained CTranslate2 Whisper model under `models` or anywhere else on a local drive, then choose the actual model folder with **Local Whisper model folder**. A local model folder must contain at least:

```text
config.json
model.bin
tokenizer.json
```

The selected local model overrides the Hugging Face model name and is loaded with local-files-only behavior. Cached managed models are also resolved with local-files-only behavior before any download is permitted. Network/UNC model folders are rejected. Clearing the local model selection returns HighlightMiner to the configured managed/cached model.

The normal model selector intentionally keeps the common choices short and ordered: **large-v3** (the HighlightMiner default), **turbo**, **medium**, and **small**. Other standard faster-whisper aliases and deliberately chosen custom Hugging Face repositories are available through **Other / advanced…** instead of filling the ordinary dropdown with every supported alias.

## Weighting presets

Presets change **only** the three signal weights. They never silently alter Whisper settings, thresholds, clip length, or timing.

| Preset | Audio | Transcript / reaction | Chat |
|---|---:|---:|---:|
| Balanced | 0.34 | 0.42 | 0.24 |
| Reaction-heavy | 0.20 | 0.60 | 0.20 |
| Chat-heavy | 0.20 | 0.25 | 0.55 |
| Audio-heavy | 0.60 | 0.25 | 0.15 |

The app editor uses `0.00–1.00` sliders. HighlightMiner normalizes the values before scoring, so the ratio is what matters. Manual changes that no longer match a preset are shown as **Custom**.

Unavailable signals receive zero effective weight and the remaining signals are renormalized. For example, Balanced becomes approximately 44.7% audio and 55.3% transcript when chat is unavailable; without transcription it becomes approximately 58.6% audio and 41.4% chat when chat exists; with neither transcript nor chat, audio becomes 100%.

If the user's configured weights assign zero weight to every signal that remains available, HighlightMiner falls back to equal weighting across the signals that actually exist rather than producing an all-zero detector.

## Reaction phrases

Reaction phrases add transcript-side evidence for moments such as surprise, laughter-like verbal reactions, swearing, or other phrases the user personally tends to say around highlight-worthy moments.

Changing reaction phrases does **not** require Whisper to transcribe the VOD again when a compatible transcript is already cached. HighlightMiner can reuse the transcript text and rescore it with the new phrase list. When speech recognition is deliberately unavailable, reaction-phrase evidence is simply absent for that run.

## JSON migration and backups

`settings.json` remains a supported interchange format, but it is no longer the primary settings store for the desktop app.

On a database that has no saved app settings yet, HighlightMiner imports the local/package `settings.json` once so existing defaults and reaction phrases are preserved. After that, SQLite is authoritative.

The Settings page can:

- **Import settings** from a validated local JSON file;
- **Export settings** to a JSON backup/share file;
- **Reset defaults** to the packaged HighlightMiner defaults.

Settings imports retain the existing security guardrails: local-file validation, JSON extension/size limits, numeric ranges, and explicit opt-in for custom Whisper model repositories. Model-download consent and the local-model path are intentionally not imported, exported, or reset through the ordinary JSON profile controls.

## CLI behavior

`HighlightMiner.exe analyze` and `python -m highlightminer analyze` use the active settings profile and local model-access preference from the selected SQLite database by default.

The CLI is deliberately non-interactive. If an uncached model is needed while permission is still **Ask**, the command exits with instructions instead of prompting or downloading. The user can explicitly choose one per-command mode:

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --allow-model-download
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --no-transcription
```

`--allow-model-download` permits a missing model download for that command only and does not change the saved desktop preference. `--no-transcription` deliberately runs without speech recognition. A saved **Never download models** preference also permits the normal CLI analysis to continue without transcription when no cached/local model exists.

An explicit JSON profile can still be used as a one-run override:

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --settings "D:\Profiles\chat-heavy.json"
```

The override is stored in that analysis run's settings snapshot but does not replace the active app profile and cannot grant recognition-model download permission.

## Reruns and learning

Every analysis run stores its own settings snapshot. This means the same VOD can be rerun with different weights or thresholds without rewriting history.

The transcript cache signature distinguishes the configured managed model from a manually selected local model. Local model file size/modification metadata is included in the cache identity so replacing a model in place invalidates transcript reuse without hashing a multi-gigabyte model on every run.

A deliberately skipped transcript is recorded as `status = skipped` with a reason, but it is **not** saved under the normal reusable Whisper signature. A later Whisper-enabled rerun can therefore still find an older compatible valid transcript instead of being blocked by an empty no-transcription run.

Candidate feature snapshots record whether transcription was available and the effective renormalized signal weights. This keeps later comparisons and preference learning from confusing “transcript score was zero” with “there was no transcript signal at all.”
