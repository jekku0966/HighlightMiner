# Building HighlightMiner for Windows

HighlightMiner can be frozen into a portable **PyInstaller onedir** application. The resulting folder contains `HighlightMiner.exe` plus its embedded Python, Streamlit, faster-whisper, CTranslate2 and pywebview runtime.

The v0.2 development build presents Streamlit inside a native Windows window using **pywebview + Microsoft Edge WebView2**. Streamlit still runs locally on `127.0.0.1:8501`, but it runs headlessly and does not open a normal browser tab.

PyInstaller's onedir mode is intentional: HighlightMiner depends on Streamlit frontend resources, CTranslate2 native binaries, pywebview/.NET resources, and user-supplied FFmpeg/CUDA runtime files. Keeping those as a portable folder is substantially easier to inspect and troubleshoot than unpacking a one-file executable on every launch.

## Local build

From the repository root in PowerShell:

```powershell
.\build_windows.ps1
```

The build script reads the version directly from `[project].version` in `pyproject.toml`. Windows packaging is currently validated for **x64** only.

```text
HighlightMiner-v<version>-windows-x64.zip
```

For `v0.2-dev`:

```text
HighlightMiner-v0.2.0.dev0-windows-x64.zip
```

The script will:

1. Read the project version and verify an x64 build host.
2. Create/reuse `.build-venv`.
3. Install HighlightMiner, tests, pywebview and PyInstaller.
4. Run the unit tests.
5. Build `HighlightMiner.exe` using `HighlightMiner.spec`.
6. Copy `settings.json` and user-facing documentation into the portable app folder.
7. Copy local `ffmpeg.exe` / `ffprobe.exe` from the repository root or `./bin` when present.
8. Copy local CUDA 12 / cuDNN 9 DLLs already placed in the repository root.
9. Smoke-test `HighlightMiner.exe --help`.
10. Run the frozen `__desktop_probe__` to verify the packaged pywebview/WinForms/WebView2 Python backend imports.
11. Run `doctor` when local FFmpeg/CUDA files are complete.
12. Create the versioned ZIP and `SHA256SUMS.txt`.

Typical output:

```text
dist/
├── HighlightMiner/
│   ├── HighlightMiner.exe
│   ├── settings.json
│   ├── ffmpeg.exe             # copied when available locally
│   ├── ffprobe.exe            # copied when available locally
│   ├── cublas64_12.dll        # copied when available locally
│   ├── cublasLt64_12.dll
│   ├── cudnn64_9.dll
│   ├── cudnn_*.dll
│   └── _internal/
├── HighlightMiner-v0.2.0.dev0-windows-x64.zip
└── SHA256SUMS.txt
```

Useful build switches:

```powershell
.\build_windows.ps1 -SkipTests
.\build_windows.ps1 -SkipZip
```

## Running the packaged app

Double-click:

```text
HighlightMiner.exe
```

With no command-line arguments, a frozen Windows build:

```text
HighlightMiner.exe
      │
      ├── starts Streamlit headlessly on 127.0.0.1:8501
      ├── waits for the local server to become ready
      └── opens the UI inside a pywebview/WebView2 desktop window
```

Closing the native window shuts down the Streamlit child and exits HighlightMiner. The **Exit HighlightMiner** button inside the UI does the same thing.

For troubleshooting, the old browser presentation remains available explicitly:

```powershell
.\HighlightMiner.exe ui --browser
```

The packaged executable also retains CLI commands:

```powershell
.\HighlightMiner.exe doctor
.\HighlightMiner.exe analyze "D:\VODs\stream.mp4" --chat "D:\VODs\stream - Chat.json"
.\HighlightMiner.exe history
.\HighlightMiner.exe import-legacy "D:\old-run\analysis.json"
.\HighlightMiner.exe export <analysis-id>
```

## Console behavior

The EXE remains a **console-capable** PyInstaller build so CLI commands still work normally when launched from PowerShell or Command Prompt.

For double-click launches, PyInstaller's `hide_console="hide-early"` mode hides the console only when the application owns that console. This keeps the normal GUI launch clean while preserving CLI output when the program is started from an existing terminal.

## Why the launcher is different when frozen

In normal source mode, `sys.executable` is Python, so HighlightMiner can launch Streamlit with:

```text
python -m streamlit run ...
```

In a PyInstaller build, `sys.executable` is `HighlightMiner.exe`, not a Python interpreter. The frozen launcher therefore starts a second `HighlightMiner.exe` process in a private Streamlit-child mode. That child invokes Streamlit inside the embedded Python runtime with headless mode enabled.

The parent waits for `http://127.0.0.1:8501`, then starts pywebview on the main thread and points its EdgeChromium/WebView2 renderer at that local address.

The raw `highlightminer/app.py` file is included as bundle data because Streamlit expects an actual Python file path.

## WebView2 requirement

The embedded Windows window requires the **Microsoft Edge WebView2 Runtime**. HighlightMiner deliberately forces pywebview's modern `edgechromium` renderer rather than silently falling back to the deprecated MSHTML/Internet Explorer engine, because modern Streamlit requires a modern web platform.

Microsoft documents the Evergreen WebView2 Runtime here:

https://developer.microsoft.com/microsoft-edge/webview2/

Windows 11 includes the Evergreen Runtime. Most Windows 10 systems also have it, but not every machine is guaranteed to. `HighlightMiner.exe doctor` reports the detected WebView2 Runtime version or marks it missing.

If the desktop shell cannot initialize, HighlightMiner shows a native Windows error dialog with the browser fallback command.

## Portable third-party runtimes

The repository does **not** commit FFmpeg, CUDA, or cuDNN binaries. The local build script only copies binaries that are already present on the build machine.

For the currently tested portable layout:

- FFmpeg / ffprobe: place them in the repository root or `./bin` before building.
- CUDA 12 / cuDNN 9: follow `CUDA_SETUP.md` and extract the DLLs into the repository root before building.
- WebView2: use the system-installed Evergreen Runtime rather than bundling a fixed Chromium runtime into the ZIP.

The resulting local ZIP will then carry the FFmpeg/CUDA files beside `HighlightMiner.exe`; WebView2 remains a Windows runtime prerequisite.

## GitHub Actions build

`.github/workflows/build-windows-exe.yml` builds the frozen Windows application on a GitHub-hosted Windows runner and uploads the versioned ZIP plus checksum.

CI verifies:

- unit tests;
- PyInstaller build;
- bundled Streamlit `app.py`;
- frozen CTranslate2 and faster-whisper imports;
- frozen pywebview/WinForms/WebView2 backend imports via `__desktop_probe__`;
- a live HTTP response from the packaged headless Streamlit backend.

CI sets `HIGHLIGHTMINER_UI_MODE=server` for the HTTP smoke test so it does not attempt to create an interactive desktop window on the build runner.

For licensing/provenance clarity, CI does not automatically download or redistribute external FFmpeg/CUDA/cuDNN binaries. The CI artifact validates the frozen Python application itself; a fully equipped local package is produced by running `build_windows.ps1` where the documented portable runtime files are present.

## Current build toolchain

- Python 3.13 in GitHub Actions.
- PyInstaller 6.21+.
- pywebview 6.2.1+ on Windows.
- UI renderer: Microsoft Edge WebView2 through pywebview's `edgechromium` backend.
- Build mode: **onedir**, console-capable with double-click console hiding.
- Release archive target: **Windows x64**.
