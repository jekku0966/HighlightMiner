# Changelog

All notable changes to HighlightMiner will be documented here.

## [Unreleased]

### Fixed

- Rerun and completed-analysis screens now explain when the saved **Never download models** policy prevents a fresh transcript and point directly to the setting required to restore speech recognition.
- Clip preview start/end fields now use `MM:SS` or `HH:MM:SS` timestamps instead of raw source seconds, with validated editing that preserves untouched internal boundaries.
- Fixed the missing-model decision buttons so downloading, choosing a local model, or continuing without speech resumes the waiting analysis job instead of reopening the same prompt.
- Cancelling a missing-model prompt now explicitly leaves model-download permission unchanged, so the app asks again on the next analysis unless the user chose a persistent model-access policy.

### Added

- Added a dedicated in-app **Settings** page backed by `highlightminer.db`, so normal desktop use no longer requires hand-editing `settings.json`.
- Added **Balanced**, **Reaction-heavy**, **Chat-heavy**, and **Audio-heavy** signal-weight presets plus a **Custom** state for manual weighting.
- Added `0.00–1.00` signal-weight sliders with normalized effective percentages and automatic no-chat renormalization.
- Added in-app editing for Whisper/inference options, highlight thresholds/timing, audio-analysis windows, and reaction phrases.
- Added Settings **Save**, **Reset defaults**, JSON **Import**, and JSON **Export** flows. Existing `settings.json` is imported once when no database settings profile exists, then SQLite becomes authoritative for the desktop app.
- Added regression tests for preset normalization/detection, database settings persistence, JSON import/export, and Settings UI module imports.
- Added `SETTINGS.md` documenting the settings database, presets, normalization, migration, and backup behavior.
- Added source-aware VOD identity and rerun history. A sampled content fingerprint groups multiple analysis runs of the same physical VOD without using the filename/path as identity.
- Added stage-aware rerun reuse for audio features, Whisper transcripts, and chat features. Compatible reruns can skip expensive processing and rerank from cached evidence.
- Added **Load latest**, **Analyze again**, and **Force full reprocess** behavior when the UI detects that a VOD has already been analyzed.
- Added CLI `analyze --no-reuse` for forcing fresh processing and `learning-stats` for reporting Keep/Reject/Unreviewed/export counts.
- Added candidate feature snapshots, review-event history, and complete export history for future preference learning.
- Added `learning_examples()` with explicit learning labels: Keep=`1`, Reject=`0`, Unreviewed=`None`.
- Added tests for sampled source identity, multiple runs per VOD, reusable feature lookup, and unlabeled Unreviewed examples.
- Added `RERUNS_AND_LEARNING.md` documenting source identity, cache invalidation, review labels, and the future-learning data contract.
- Added a native Windows desktop shell for `v0.2-dev` using pywebview + Microsoft Edge WebView2. The local Streamlit backend now runs headlessly and is presented inside the HighlightMiner application window instead of opening a normal browser tab.
- Added `highlightminer/desktop.py` for UI-mode resolution, Streamlit readiness checks, native-window lifecycle handling, browser fallback, and packaged desktop-runtime probing.
- Added `HighlightMiner.exe ui --browser` as an explicit troubleshooting/development fallback.
- Added Windows `doctor` checks for pywebview importability and the installed WebView2 Runtime version.
- Added desktop-shell unit tests and a frozen `__desktop_probe__` packaging smoke test.

### Changed

- Analysis cannot start until both a VOD and work folder are selected, and changing the VOD clears any stale rerun decision tied to the previous source.
- Streamlit now uses its supported minimal toolbar mode in source, packaged desktop, and browser-fallback launches; app headings no longer expose permalink anchors.
- Native-window close and the in-app **Exit HighlightMiner** control are now locked while a non-cancellable analysis or export stage is active, preventing an apparent app exit from terminating the shared worker mid-operation.
- The desktop Mine/Review flow now reads the active Settings profile from SQLite; each analysis still stores an immutable settings snapshot for historical comparison and future preference learning.
- The old Settings-file picker was removed from normal Mine/Review UI. JSON remains a validated migration/interchange/backup format rather than the primary desktop configuration surface.
- PyInstaller explicitly bundles the Settings/Mine UI modules that are dynamically imported by Streamlit, and Windows packaging includes `SETTINGS.md`.
- Existing v0.2 SQLite databases are migrated in place to the source/run schema; existing generated analysis history is retained.
- Changing only scoring settings no longer requires another Whisper pass when a compatible transcript is available. Reaction phrases rescore cached transcript text without invalidating transcription.
- Chat reuse keys include a full SHA-256 of the selected chat file; VOD source fingerprints are deliberately sampled identity keys rather than security/integrity hashes.
- Exports no longer silently overwrite a same-named clip; the next available numbered suffix is used and every export is recorded in SQLite.
- Closing the native HighlightMiner window now shuts down the child Streamlit server and exits the application cleanly; the existing in-app Exit button closes both as well.
- The packaged Streamlit server is now always headless and uses `127.0.0.1` consistently for server/browser addressing.
- PyInstaller now collects pywebview resources, explicitly keeps the WinForms/EdgeChromium/pythonnet imports, and uses `hide_console="hide-early"` so double-click launches hide their owned console while terminal-launched CLI commands retain output.
- Windows packaging now depends on `pywebview>=6.2.1,<7` and requires the system Microsoft Edge WebView2 Runtime for the embedded desktop UI.
- GitHub Actions now verifies the frozen pywebview/WebView2 backend imports and uses `HIGHLIGHTMINER_UI_MODE=server` for non-interactive Streamlit HTTP smoke testing.
- Updated README, Windows build, v0.2 architecture, security, and attribution documentation for the embedded desktop architecture.

## [0.1.2] - 2026-08-17

### Changed

- Updated `setup.ps1` to match the current portable FFmpeg/ffprobe workflow.
- Setup now runs from the repository root, reuses an existing `.venv`, verifies Python 3.10+, installs HighlightMiner, and runs `highlightminer doctor` automatically.
- Setup now documents the `./bin`, project-root, and system-`PATH` FFmpeg lookup locations when diagnostics need attention.
- Setup now points Twitch users to TwitchDownloader as the recommended companion workflow for obtaining a matching VOD + JSON chat export.
- Added portable Windows CUDA 12/cuDNN 9 runtime support using DLLs placed directly beside `run.bat`.
- `run.bat` and the transcription runtime now explicitly expose the HighlightMiner root to Windows DLL loading.
- `doctor` now checks `cublas64_12.dll`, `cublasLt64_12.dll`, and `cudnn64_9.dll` so a visible NVIDIA GPU no longer produces a false-green result when the inference runtime is missing.
- Added `CUDA_SETUP.md` with a direct download link for Purfview's `cuBLAS.and.cuDNN_CUDA12_win_v3.7z` bundle and exact root-folder extraction instructions.
- Added Git ignore rules for locally downloaded CUDA/cuDNN DLLs and attribution for NVIDIA/Purfview runtime components.
- Fixed the Streamlit review UI launcher by switching `highlightminer/app.py` to absolute package imports, so `python -m highlightminer ui` no longer fails with `ImportError: attempted relative import with no known parent package`.
- Review playback now generates and caches a short browser-friendly H.264 preview for the selected candidate instead of handing the full multi-hour source VOD to Streamlit.
- Review previews are capped to 1280px width / 30 fps with lightweight encoding and are regenerated only when a candidate's timing changes.
- The review video player now displays at a compact 640px width while keeping the cached preview file at its existing quality.
- Replaced deprecated Streamlit `use_container_width=True` arguments with `width="stretch"`.
- Added a sidebar **Exit HighlightMiner** button. The CLI now supervises the Streamlit child process, accepts a browser-triggered shutdown request, asks the server to stop cleanly, and falls back to terminate/kill only if the normal stop does not complete.
- Added frozen-application path handling so `settings.json`, work folders, FFmpeg, and portable CUDA/cuDNN files resolve beside `HighlightMiner.exe` in a PyInstaller build while retaining repository-root behavior in source mode.
- Added a frozen Streamlit launcher: packaged builds spawn `HighlightMiner.exe` in a private child mode and invoke Streamlit from the embedded Python runtime instead of incorrectly treating the EXE as a Python interpreter.
- Double-clicking a frozen `HighlightMiner.exe` now launches the UI automatically; packaged CLI subcommands remain available.
- The packaged Streamlit server skips Streamlit's first-run email prompt, disables Streamlit usage-statistics telemetry, runs with development mode disabled, and binds only to `127.0.0.1:8501`.
- Added `HighlightMiner.spec`, the `packaging` dependency group, frozen-path tests, and `build_windows.ps1` for reproducible PyInstaller onedir Windows builds.
- The Windows build script runs tests, freezes the app, copies user-facing files plus locally supplied FFmpeg/CUDA runtime files, smoke-tests the executable, and creates a versioned `dist/HighlightMiner-v<version>-windows-x64.zip` archive.
- The project version in `pyproject.toml` is now the source of truth for Windows release archive naming.
- Windows release packaging explicitly validates the x64 architecture rather than silently producing a misleading package name on another architecture.
- GitHub Actions reads the same project version and publishes a matching version/platform/architecture-named build artifact.
- Added `BUILD_WINDOWS.md` documenting the portable executable layout, build process, frozen launcher behavior, third-party runtime policy, and release archive naming convention.
- Added a GitHub Actions Windows packaging workflow. A clean Windows runner validates unit tests, the PyInstaller build, the bundled Streamlit script, frozen CTranslate2/faster-whisper imports, a live HTTP response from the packaged Streamlit server, and artifact creation before the build is accepted.
- Added native Windows **Browse** controls for VODs, chat files, work folders, settings, existing `analysis.json` files, and export folders. The picker returns filesystem paths directly instead of uploading large media through the browser.
- Refreshed the Streamlit UI with a dedicated HighlightMiner dark graphite/amber theme, clearer section labels, and a more app-like header. The supported `.streamlit/config.toml` theme is copied into portable Windows builds automatically.
- Added a per-VOD **Content / Game** label in Streamlit and a matching CLI `--content` option. The normalized label is stored in `analysis.json` and copied onto each ranked candidate so future preference learning has historical context.
- Kept clips now export into a category subfolder beneath the selected clips directory, such as `clips/Overwatch 2/`. Blank or legacy analyses fall back to `Unsorted`.
- Category folder names preserve readable Unicode while sanitizing invalid Windows path characters and reserved device names.
- Added dedicated `v0.1.2` release notes covering the Windows package, install flow, compatibility, and early-alpha caveats.

## [0.1.1] - 2026-08-16

### Changed

- Added portable FFmpeg/ffprobe discovery.
- HighlightMiner now checks `./bin`, then the project root, then system `PATH` for FFmpeg executables.
- Clip export now uses the resolved FFmpeg path instead of assuming `ffmpeg` is globally available.
- `doctor` now reports the actual resolved local executable paths.
- Added `.gitignore` rules for local FFmpeg binaries and generated media.
- Added `.gitattributes` line-ending rules.
- Updated README setup instructions to match portable FFmpeg support.
- Added FFmpeg/ffprobe download links, a known-good Windows test build (`descriptinc/ffmpeg-ffprobe-static` `b6.1.2-rc.1`), and version-check instructions.
- Added approximate analysis-time guidance for long VODs.
- Documented TwitchDownloader as the recommended companion workflow for obtaining a consistent Twitch VOD + matching JSON chat pair during current testing.
- Added explicit thanks and attribution for `lay295` and TwitchDownloader contributors while clarifying that TwitchDownloader is not bundled or invoked by HighlightMiner.

## [0.1.0] - 2026-08-16

### Added

- Local FFmpeg/ffprobe media handling.
- Audio-energy and onset-style feature extraction.
- `faster-whisper` transcription with CUDA detection and CPU fallback.
- Configurable reaction/laughter/transcript heuristics.
- JSON/JSONL/CSV chat parsing and burst scoring.
- Weighted audio/transcript/chat signal fusion.
- Candidate merging, ranking, context windows, and overlap deduplication.
- Streamlit review UI with Keep/Reject/timing/title edits.
- NVENC-first H.264 export with x264 fallback.
- CLI commands: `doctor`, `analyze`, `ui`, `export`.
- Unit tests for text scoring, chat bursts, and candidate detection.
- GitHub-ready documentation, attribution notes, MIT license, and CI workflow.
