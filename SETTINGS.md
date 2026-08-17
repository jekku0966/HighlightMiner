# HighlightMiner settings

`v0.2-dev` manages normal user settings inside the application. The active profile is stored in `highlightminer.db`; users no longer need to edit `settings.json` for normal use.

## Settings page

Open **⚙️ Settings** from the HighlightMiner sidebar. The page is split into:

- **Analysis engine** — Whisper model, device, compute type, language, beam size, and VAD;
- **Detection & weights** — candidate threshold/count, clip timing, audio analysis windows, and signal weighting;
- **Reaction phrases** — one phrase per line;
- **Import / Export** — migrate, back up, or share a JSON settings profile.

Press **Save settings** to make the editor state active. Saved changes apply to future analysis runs and reruns. Existing analyses retain the exact settings snapshot they were created with.

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

Settings imports retain the existing security guardrails: local-file validation, JSON extension/size limits, numeric ranges, and explicit opt-in for custom Whisper model repositories.

## CLI behavior

`HighlightMiner.exe analyze` and `python -m highlightminer analyze` use the active settings profile from the selected SQLite database by default, matching the desktop app.

An explicit JSON profile can still be used as a one-run override:

```powershell
HighlightMiner.exe analyze "D:\VODs\stream.mp4" --settings "D:\Profiles\chat-heavy.json"
```

The override is stored in that analysis run's settings snapshot but does not replace the active app profile.

## Reruns and learning

Every analysis run stores its own settings snapshot. This means the same VOD can be rerun with different weights or thresholds without rewriting history.

That is useful for future preference learning because HighlightMiner can later compare explicit Keep/Reject labels against the exact detector configuration that produced each candidate.
