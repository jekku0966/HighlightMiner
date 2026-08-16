# Changelog

All notable changes to HighlightMiner will be documented here.

## [Unreleased]

### Changed

- Updated `setup.ps1` to match the current portable FFmpeg/ffprobe workflow.
- Setup now runs from the repository root, reuses an existing `.venv`, verifies Python 3.10+, installs HighlightMiner, and runs `highlightminer doctor` automatically.
- Setup now documents the `./bin`, project-root, and system-`PATH` FFmpeg lookup locations when diagnostics need attention.
- Setup now points Twitch users to TwitchDownloader as the recommended companion workflow for obtaining a matching VOD + JSON chat export.

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
