# HighlightMiner v0.1.2

**Tag:** `v0.1.2`  
**Release title:** `HighlightMiner v0.1.2`  
**Windows asset:** `HighlightMiner-v0.1.2-windows-x64.zip`

HighlightMiner v0.1.2 is the first release intended to feel like a portable Windows application rather than a Python project somebody has to assemble by hand.

## Highlights

- Portable PyInstaller **Windows x64** application with embedded Streamlit/faster-whisper runtime.
- Double-click `HighlightMiner.exe` to launch the local review UI.
- Native Windows **Browse** buttons for VODs, chat files, settings, work folders, existing analyses, and export folders.
- Dark graphite/amber Streamlit theme.
- Browser-safe lightweight H.264 candidate previews instead of loading an entire multi-hour VOD into the player.
- Sidebar **Exit HighlightMiner** control for clean application shutdown.
- Content/game categorization for analyzed VODs.
- Kept highlights are exported into category folders such as `clips/Overwatch 2/` or `clips/Just Chatting/`.
- Blank or legacy categories fall back to `Unsorted`.
- Category names are sanitized for Windows filesystem safety while retaining readable Unicode names.
- Portable FFmpeg/ffprobe lookup beside the application.
- Portable CUDA 12 / cuDNN 9 runtime support for GPU Whisper inference.
- `doctor` diagnostics for FFmpeg, NVENC, CTranslate2, CUDA visibility, cuBLAS/cuDNN, and faster-whisper.
- Clean Windows CI verifies unit tests, the frozen application, bundled dependencies, and a live localhost Streamlit response.
- Windows release ZIP names now derive automatically from the version in `pyproject.toml` and include platform/architecture.

## Install

1. Download `HighlightMiner-v0.1.2-windows-x64.zip` from this release.
2. Extract the entire `HighlightMiner` folder somewhere writable.
3. Double-click `HighlightMiner.exe`.
4. Choose a VOD, optional chat export, and a **Content / Game** label.
5. Analyze, review candidates, mark clips **Keep**, and export them.

HighlightMiner processes VODs locally. No cloud API is required for v0.1.2.

## Notes

- This is an **early alpha** release.
- The Windows executable is currently unsigned, so Windows SmartScreen may warn on first launch.
- The selected faster-whisper model may need to download on first use if it is not already cached.
- One content/game label applies to the whole VOD in v0.1.2. Timestamp-based category changes can come later.
- Keep/Reject preference learning is intentionally reserved for the v0.2 line; v0.1.2 begins storing category context that can be useful for that future learner.

## Upgrade / compatibility

Existing v0.1 analyses remain usable. Analyses created before content categorization was added are treated as `Unsorted` during export.
