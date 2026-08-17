# Third-party dependencies and provenance

This file documents the external projects and public interfaces used by HighlightMiner.

## Provenance policy

HighlightMiner was written as a new implementation. No substantial third-party source file or code block was intentionally copied into this repository.

Where HighlightMiner invokes an external library or executable, the integration is written against that project's public API/CLI documentation. If future contributors incorporate or adapt third-party source code, they should add an entry here with the exact source, license, and affected files.

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

- Purpose: local review UI engine.
- Used in: `highlightminer/app.py` and the embedded launcher path in `highlightminer/cli.py`.
- Public APIs referenced include `st.video`, `st.dataframe`, `st.session_state`, form/input widgets, status/progress elements, and layout primitives.
- Documentation: https://docs.streamlit.io/
- Source: https://github.com/streamlit/streamlit
- License: see upstream project.

In v0.2 on Windows, Streamlit runs headlessly on loopback and is displayed inside the native pywebview/WebView2 shell rather than opening a normal browser tab.

No Streamlit source code is vendored in HighlightMiner.

### pywebview

- Purpose: lightweight native desktop window that hosts the local Streamlit UI on Windows.
- Used in: `highlightminer/desktop.py` and Windows packaging.
- Public APIs referenced include `webview.create_window`, `webview.start`, `webview.settings`, `Window.destroy`, and the `edgechromium` renderer selection.
- Documentation: https://pywebview.flowrl.com/
- Source: https://github.com/r0x0r/pywebview
- Upstream license: BSD-3-Clause.
- Current v0.2 dependency range: `pywebview>=6.2.1,<7` on Windows.

No pywebview source code is vendored in HighlightMiner. PyInstaller collects pywebview's installed package resources into the Windows application bundle.

### Microsoft Edge WebView2 Runtime

- Purpose: modern Chromium rendering engine used by pywebview's Windows `edgechromium` backend.
- Documentation/downloads: https://developer.microsoft.com/microsoft-edge/webview2/
- Distribution guidance: https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution
- Relationship: system runtime prerequisite for the v0.2 embedded Windows UI; not committed to this repository and not currently bundled into HighlightMiner ZIPs.

HighlightMiner intentionally requires the modern WebView2 backend for its embedded Streamlit window rather than silently falling back to legacy MSHTML.

## External executables / runtime libraries

### FFmpeg / ffprobe

- Purpose: media probing, PCM audio extraction, preview generation, and final H.264/AAC clip creation.
- Used in: `highlightminer/media.py`, `highlightminer/export.py`, `highlightminer/doctor.py`.
- CLI documentation referenced: https://ffmpeg.org/ffmpeg.html and https://ffmpeg.org/ffmpeg-all.html
- Project: https://ffmpeg.org/
- License: FFmpeg's licensing depends on build configuration; see the upstream project.

HighlightMiner does not commit FFmpeg binaries or FFmpeg source.

### NVIDIA CUDA / cuBLAS / cuDNN

- Purpose: GPU-accelerated CTranslate2 / faster-whisper inference on NVIDIA GPUs.
- Current faster-whisper requirement used by the portable setup: cuBLAS for CUDA 12 and cuDNN 9 for CUDA 12.
- NVIDIA CUDA: https://developer.nvidia.com/cuda-zone
- NVIDIA cuBLAS: https://developer.nvidia.com/cublas
- NVIDIA cuDNN: https://developer.nvidia.com/cudnn
- License/terms: see NVIDIA's upstream distribution terms.

For the documented portable Windows setup, HighlightMiner points users to the CUDA 12 + cuDNN 9 archive published by **Purfview / whisper-standalone-win**, which is also referenced by faster-whisper's upstream documentation:

- Project: https://github.com/Purfview/whisper-standalone-win
- Library release: https://github.com/Purfview/whisper-standalone-win/releases/tag/libs
- Documented bundle: `cuBLAS.and.cuDNN_CUDA12_win_v3.7z`

The DLLs are downloaded separately by the user and placed beside the app/build files. They are ignored by Git and are **not committed by HighlightMiner**.

Thank you to **Purfview** for maintaining the convenient Windows runtime archive used by the portable setup instructions.

## Recommended companion tool / input-format reference

### TwitchDownloader

- Creator / maintainer: [lay295](https://github.com/lay295), with contributions from the TwitchDownloader community.
- Project: https://github.com/lay295/TwitchDownloader
- Upstream license: MIT.
- Purpose: download Twitch VODs and matching chat exports in a repeatable way before processing them with HighlightMiner.
- Recommended HighlightMiner workflow: download the VOD and export the matching chat as **JSON**, then give those two local files to HighlightMiner.
- Relationship: recommended companion tool and compatibility reference; **not** a HighlightMiner runtime dependency.
- Current integration status: HighlightMiner does not invoke TwitchDownloader automatically. Direct TwitchDownloaderCLI integration is a possible future improvement after the core pipeline has been validated on real VODs.

HighlightMiner's chat parser intentionally recognizes common Twitch-style fields such as `content_offset_seconds` and nested message text. This makes TwitchDownloader JSON a useful common input target while still allowing other JSON/JSONL/CSV formats.

No TwitchDownloader code is vendored, copied, or imported by HighlightMiner.

### Thank you

A specific thank you to **lay295 and the TwitchDownloader contributors** for building and maintaining a practical open-source tool for downloading Twitch VODs and chat. HighlightMiner does not need to reinvent Twitch downloading because that problem already has a well-established open-source solution.

## AI-assisted development

The implementation and documentation have been produced with AI coding assistance from OpenAI's ChatGPT, based on project requirements discussed interactively. The resulting code should be reviewed, tested, and maintained like any human-authored code.

AI-generated implementation is not a substitute for third-party license compliance. Dependencies and models remain governed by their respective upstream terms.
