# Third-party dependencies and provenance

This file documents the external projects and public interfaces used by HighlightMiner.

## Provenance policy

HighlightMiner v0.1 was written as a new implementation. No substantial third-party source file or code block was intentionally copied into this repository.

Where HighlightMiner invokes an external library or executable, the integration was written against that project's public API/CLI documentation. If future contributors incorporate or adapt third-party source code, they should add an entry here with the exact source, license, and affected files.

## Runtime dependencies

### faster-whisper

- Purpose: local speech-to-text transcription.
- Used in: `highlightminer/transcribe.py`.
- Public API referenced: `WhisperModel`, `WhisperModel.transcribe`, returned segment metadata, VAD option.
- Source/docs: https://github.com/SYSTRAN/faster-whisper
- Upstream license: MIT.
- Notes: the project README documents GPU requirements and automatic model retrieval from Hugging Face Hub when loading a named model.

No faster-whisper source code is vendored in HighlightMiner.

### CTranslate2

- Purpose: inference backend used by faster-whisper; CUDA-device and supported-compute-type checks are also queried by `highlightminer/doctor.py` / `highlightminer/transcribe.py`.
- Source/docs: https://github.com/OpenNMT/CTranslate2
- License: see upstream repository.

No CTranslate2 source code is vendored in HighlightMiner.

### NumPy

- Purpose: numeric array processing, percentiles, normalization, rolling/timeline operations.
- Used in: audio/chat/scoring modules.
- Source/docs: https://numpy.org/
- License: see upstream project.

No NumPy source code is vendored in HighlightMiner.

### Streamlit

- Purpose: local browser review UI.
- Used in: `highlightminer/app.py`.
- Public APIs referenced include `st.video`, `st.dataframe`, `st.session_state`, form/input widgets, status/progress elements, and layout primitives.
- Documentation: https://docs.streamlit.io/
- Source: https://github.com/streamlit/streamlit
- License: see upstream project.

No Streamlit source code is vendored in HighlightMiner.

## External executable

### FFmpeg / ffprobe

- Purpose: media probing, PCM audio extraction, and final H.264/AAC clip creation.
- Used in: `highlightminer/media.py`, `highlightminer/export.py`, `highlightminer/doctor.py`.
- CLI documentation referenced: https://ffmpeg.org/ffmpeg.html and https://ffmpeg.org/ffmpeg-all.html
- Project: https://ffmpeg.org/
- License: FFmpeg's licensing depends on build configuration; see the upstream project.

HighlightMiner does not bundle FFmpeg binaries or FFmpeg source.

## Format/reference compatibility

### TwitchDownloader

- Relationship: compatibility reference only; not a runtime dependency.
- Purpose: TwitchDownloader is a common source of Twitch chat JSON files, so HighlightMiner's generic chat parser accepts common timestamp/message field shapes that can occur in Twitch-style exports.
- Source: https://github.com/lay295/TwitchDownloader
- Upstream license: MIT.

No TwitchDownloader code is vendored or imported.

## AI-assisted development

The initial v0.1 implementation and documentation were produced with AI coding assistance from OpenAI's ChatGPT, based on project requirements discussed interactively. The resulting code should be reviewed, tested, and maintained like any human-authored code.

AI-generated implementation is not a substitute for third-party license compliance. Dependencies and models remain governed by their respective upstream terms.
