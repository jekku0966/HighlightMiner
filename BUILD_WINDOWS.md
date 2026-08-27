# Building HighlightMiner for Windows

HighlightMiner can be frozen into a portable **PyInstaller onedir** application. The resulting folder contains `HighlightMiner.exe` plus its embedded Python, Streamlit, faster-whisper, CTranslate2 and pywebview runtime.

The v0.2 development build presents Streamlit inside a native Windows window using **pywebview + Microsoft Edge WebView2**. Streamlit still runs locally on `127.0.0.1:8501`, but it runs headlessly and does not open a normal browser tab.

PyInstaller's onedir mode is intentional: HighlightMiner depends on Streamlit frontend resources, CTranslate2 native binaries, pywebview/.NET resources, and user-supplied FFmpeg/CUDA runtime files. Keeping those as a portable folder is substantially easier to inspect and troubleshoot than unpacking a one-file executable on every launch.

## Development/local build

From the repository root in PowerShell:

```powershell
.\build_windows.ps1
```

The build uses `tools\project_version.py` to read and validate `[project].version` from `pyproject.toml`. Windows packaging is currently validated for **x64** only.

The public builder is intentionally kept in the source repository so packaging remains testable and contributors can reproduce development builds. A ZIP produced directly by this script is a **local/development convenience archive**, not an official HighlightMiner release asset.

```text
HighlightMiner-v<version>-windows-x64.zip
```

For the current v0.2 development version:

```text
HighlightMiner-v0.2.0.dev0-windows-x64.zip
```

The script will:

1. Verify an x64 build host.
2. Create or reuse `.build-venv`, recreating it when its Python is unreadable or older than 3.10.
3. Install HighlightMiner, tests, pywebview and PyInstaller.
4. Read and validate the project version through the shared TOML-aware helper.
5. Run the unit tests.
6. Build `HighlightMiner.exe` using `HighlightMiner.spec`.
7. Copy `settings.json` and user-facing documentation into the portable app folder.
8. Copy local `ffmpeg.exe` / `ffprobe.exe` from the repository root or `./bin` when present.
9. Copy only the documented CUDA 12 / cuDNN 9 DLL allowlist from `runtime\cuda`.
10. Smoke-test `HighlightMiner.exe --help`.
11. Run the frozen `__desktop_probe__` to verify the packaged pywebview/WinForms/WebView2 Python backend imports.
12. Run `doctor` when local FFmpeg/CUDA files are complete.
13. Create the versioned ZIP and `SHA256SUMS.txt` unless `-SkipZip` is supplied.

Typical local output:

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

## Build-environment validation

The builder requires Python 3.10 or newer. Before reusing `.build-venv`, it reads the interpreter version from `.build-venv\Scripts\python.exe`. If the version cannot be read or is older than Python 3.10, the generated environment is removed and recreated.

When creating a new build environment, the script prefers the Windows `py -3` launcher when it resolves to a compatible interpreter, then falls back to `python` on `PATH`. If neither produces Python 3.10+, the build stops with a clear error instead of creating an unsupported environment.

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

Closing the native window shuts down the Streamlit child and exits HighlightMiner. The **Exit HighlightMiner** button inside the UI does the same thing. While a non-cancellable analysis or export stage is active, both shutdown paths stay locked until the work finishes or reaches a safe waiting state.

For troubleshooting, the browser presentation remains available explicitly:

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

Windows 11 includes the Evergreen Runtime. Most Windows 10 systems also have it, but not every machine is guaranteed to. `HighlightMiner.exe doctor` reports the detected runtime when present.

If the desktop shell cannot initialize, HighlightMiner shows a native Windows error dialog with the browser fallback command.

## Portable third-party runtimes

The repository does **not** commit FFmpeg, CUDA, or cuDNN binaries. The local build script only copies binaries that are already present on the build machine.

For the currently tested portable layout:

- FFmpeg / ffprobe: place them in the repository root or `./bin` before building.
- CUDA 12 / cuDNN 9: follow `CUDA_SETUP.md` and extract the portable DLLs into `runtime\cuda` before building.
- WebView2: use the system-installed Evergreen Runtime rather than bundling a fixed Chromium runtime into the ZIP.

The CUDA packager copies an exact allowlist from `runtime\cuda`; it does not scan the repository root for DLL families. The resulting local package carries the selected FFmpeg/CUDA files beside `HighlightMiner.exe`; WebView2 remains a Windows runtime prerequisite.

## Bundle-size policy

`HighlightMiner.spec` deliberately uses PyInstaller's conservative `collect_all` behavior for Streamlit, faster-whisper, CTranslate2 and pywebview. These packages use dynamic imports, native libraries and runtime data that can appear unused during static analysis.

Trim those collections only after clean-machine Windows validation proves the smaller bundle still passes the frozen doctor, desktop/WebView2 startup, CPU transcription and real CUDA transcription. Optimize one package at a time so dependency upgrades can be compared against a known-good package set.

## GitHub Actions: validation only

`.github/workflows/build-windows-exe.yml` builds the frozen Windows application on a GitHub-hosted Windows runner **only to validate packaging**. It invokes `build_windows.ps1 -SkipZip` and does not upload an EXE, Windows ZIP, or checksum artifact.

CI verifies:

- unit tests;
- PyInstaller build;
- bundled Streamlit `app.py` and user documentation;
- frozen CTranslate2 and faster-whisper imports;
- frozen pywebview/WinForms/WebView2 backend imports via `__desktop_probe__`;
- a live HTTP response from the packaged headless Streamlit backend;
- that the validation run did not create a release ZIP.

CI sets `HIGHLIGHTMINER_UI_MODE=server` for the HTTP smoke test so it does not attempt to create an interactive desktop window on the build runner. Its process cleanup is guarded so a failed `Start-Process` cannot mask the original launch error with a null-process cleanup failure.

For licensing/provenance clarity, public CI does not automatically download or redistribute external FFmpeg/CUDA/cuDNN binaries and does not publish compiled development artifacts.

## Official releases

Official Windows release packaging is deliberately separated from ordinary public CI. The maintainer builds from an exact public release tag using a separate maintainer-only release workflow that:

- requires the tag and `pyproject.toml` version to match;
- stages trusted local FFmpeg and the explicit CUDA/cuDNN allowlist;
- runs the public builder/tests;
- requires the packaged `doctor` check to pass;
- smoke-tests the frozen Streamlit backend;
- creates the versioned Windows ZIP;
- generates `SHA256SUMS.txt` and `RELEASE_MANIFEST.json` recording source-commit and bundled-runtime hashes.

Those files are then manually attached to the public GitHub Release. **Only Windows binaries attached to the HighlightMiner GitHub Releases page by the maintainer are official project binaries.** GitHub automatically provides source-code ZIP and tar.gz archives from the corresponding public tag.

HighlightMiner is open source, so nothing prevents a third party from compiling the public source themselves. Such binaries are third-party builds, not official release assets.

## Current build toolchain

- Python 3.13 in GitHub Actions.
- Local builder: Python 3.10+ with validation/recreation of `.build-venv`.
- PyInstaller 6.21+.
- pywebview 6.2.1+ on Windows.
- UI renderer: Microsoft Edge WebView2 through pywebview's `edgechromium` backend.
- Build mode: **onedir**, console-capable with double-click console hiding.
- Official release target: **Windows x64**.
