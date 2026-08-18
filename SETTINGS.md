# HighlightMiner settings

`v0.2-dev` manages normal user settings inside the application. The active profile is stored in `highlightminer.db`; users no longer need to edit `settings.json` for normal use.

## Settings page

Open **⚙️ Settings** from the HighlightMiner sidebar. The page is split into:

- **Analysis engine** — model access/download permission, local model folder, Whisper model, device, compute type, language, beam size, and VAD;
- **Detection & weights** — candidate threshold/count, clip timing, audio analysis windows, and signal weighting;
- **Reaction phrases** — one phrase per line;
- **Import / Export** — migrate, back up, or share a JSON settings profile.

Press **Save settings** to make the normal editor state active. Saved changes apply to future analysis runs and reruns. Existing analyses retain the exact settings snapshot they were created with.

## Recognition-model downloads and local models

HighlightMiner does not silently opt a user into recognition-model downloads. On a fresh database the model-download permission starts as **Ask before any download** and the desktop UI presents an explicit choice:

- **Allow model downloads** — the selected faster-whisper model may be downloaded from Hugging Face when it is not already available locally;
- **No model downloads** — HighlightMiner only uses an already cached model or a manually selected local model.

The choice is stored in the local SQLite database and can be changed later under **Settings → Analysis engine → Model access**. It is deliberately separate from imported/exported JSON settings, so importing a profile cannot grant network-download permission on the user's behalf.

HighlightMiner automatically creates a local `models` directory beside the application/source root. A user can place a manually obtained CTranslate2 Whisper model there or anywhere else on a local drive, then choose the actual model folder with **Local Whisper model folder**. A local model folder must contain at least:

```text
config.json
model.bin
tokenizer.json
```

The selected local model overrides the Hugging Face model name and is loaded offline. Network/UNC model folders are rejected. Clearing the local model selection returns HighlightMiner to the configured managed/cached model.

If downloads are not allowed and the selected managed model is not already cached, analysis stops with a clear message instead of downloading anything.

## Weighting presets

Presets change **only** the three signal weights. They never silently alter Whisper settings, thresholds, clip length, or timing.

| Preset | Audio | Transcript / reaction | Chat |
|---|---:|---:|---:|
| Balanced | 0.34 | 0.42 | 0.24 |
| Reaction-heavy | 0.20 | 0.60 | 0.20 |
| Chat-heavy | 0.20 | 0.25 | 0.55 |
| Audio-heavy | 0.60 | 0.25 | 0.15 |

The app editor uses `0.00–1.00` sliders. HighlightMiner normalizes the three values before scoring, so the ratio is what matters. Manual changes that no longer match a preset are shown as **Custom**.

If no chat file is supplied, the chat contribution becomes zero and audio/transcript are automatically renormalized. For example, Balanced becomes approximately 44.7% audio and 55.3% transcript when chat is unavailable.

## Reaction phrases

Reaction phrases add transcript-side evidence for moments such as surprise, laughter-like verbal reactions, swearing, or other phrases the user personally tends to say around highlight-worthy moments.

Changing reaction phrases does **not** require Whisper to transcribe the VOD again when a compatible transcript is already cached. HighlightMiner can reuse the transcript text and rescore it with the new phrase list.

## JSON migration and backups

`settings.json` remains a supported interchange format, but it is no longer the primary settings store for the desktop app.

On a database that has no saved app settings yet, HighlightMiner imports the local/package `settings.json` once so existing v0.1/v0.2-dev behavior and reaction phrases are preserved. After that, SQLite is authoritative.

The Settings page can:

- **Import settings** from a validated local JSON file;
- **Export settings** to a JSON backup/share file;
- **Reset defaults** to the packaged HighlightMiner defaults.

Settings imports retain the existing security guardrails: local-file validation, JSON extension/size limits, numeric ranges, and explicit opt-in for custom Whisper model repositories. Model-download consent and the local-model path are intentionally not imported, exported, or reset through the ordinary JSON profile controls.

## CLI behavior

`HighlightMiner.exe analyze` and `python -m highlightminer analyze` use the active settings profile and local model-access preference from the selected SQLite database by default, matching the desktop app.

An explicit JSON profile can still be used as a one-run override:

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --settings "D:\Profiles\chat-heavy.json"
```

The override is stored in that analysis run's settings snapshot but does not replace the active app profile and cannot grant recognition-model download permission. If the selected model is not cached and downloads have not been explicitly allowed in the database, CLI analysis stops with the same model-access error used by the desktop app.

## Reruns and learning

Every analysis run stores its own settings snapshot. This means the same VOD can be rerun with different weights or thresholds without rewriting history.

The transcript cache signature also distinguishes the configured managed model from a manually selected local model. Local model file size/modification metadata is included in the cache identity so replacing a model in place invalidates transcript reuse without hashing a multi-gigabyte model on every run.

That is useful for future preference learning because HighlightMiner can later compare explicit Keep/Reject labels against the exact detector configuration that produced each candidate.
