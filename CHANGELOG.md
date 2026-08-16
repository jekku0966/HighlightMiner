# Changelog

All notable changes to HighlightMiner will be documented here.

## [Unreleased]

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
- The packaged Streamlit server now skips Streamlit's first-run email prompt, disables Streamlit usage-statistics telemetry, runs with development mode disabled, and binds only to `127.0.0.1:8501`.
- Added `HighlightMiner.spec`, the `packaging` dependency group, frozen-path tests, and `build_windows.ps1` for reproducible PyInstaller onedir Windows builds.
- The Windows build script runs tests, freezes the app, copies user-facing files plus locally supplied FFmpeg/CUDA runtime files, smoke-tests the executable, and creates `dist/HighlightMiner-Windows-x64.zip`.
- Added `BUILD_WINDOWS.md` documenting the portable executable layout, build process, frozen launcher behavior, and third-party runtime policy.
- Added a GitHub Actions Windows packaging workflow. A clean Windows runner now validates all unit tests, the PyInstaller build, the bundled Streamlit script, frozen CTranslate2/faster-whisper imports, a live HTTP response from the packaged Streamlit server, and artifact creation before the build is accepted.

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
