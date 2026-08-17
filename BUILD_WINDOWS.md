# Building HighlightMiner for Windows

HighlightMiner can be frozen into a portable **PyInstaller onedir** application. The resulting folder contains `HighlightMiner.exe` plus its embedded Python/Streamlit/faster-whisper runtime.

PyInstaller's onedir mode is intentional here: HighlightMiner depends on Streamlit frontend resources, CTranslate2 native binaries, and user-supplied FFmpeg/CUDA runtime files. Keeping those as a portable folder is substantially easier to inspect and troubleshoot than unpacking a single-file executable on every launch.

## Local build

From the repository root in PowerShell:

```powershell
.\build_windows.ps1
```

The build script reads the release version directly from `[project].version` in `pyproject.toml`. Windows release packaging is currently validated for **x64** only. The portable archive is therefore named using the project version, platform, and architecture:

```text
HighlightMiner-v<version>-windows-x64.zip
```

For example, version `0.1.2` produces:

```text
HighlightMiner-v0.1.2-windows-x64.zip
```

The script will:

1. Read the project version from `pyproject.toml` and verify an x64 build host.
2. Create/reuse `.build-venv`.
3. Install HighlightMiner, tests, and PyInstaller.
4. Run the unit tests.
5. Build `HighlightMiner.exe` using `HighlightMiner.spec`.
6. Copy `settings.json` and user-facing documentation into the portable app folder.
7. Copy local `ffmpeg.exe` / `ffprobe.exe` from the repository root or `./bin` when present.
8. Copy local CUDA 12 / cuDNN 9 DLLs already placed in the repository root.
9. Smoke-test `HighlightMiner.exe --help`.
10. Run the packaged `doctor` check when the local FFmpeg and CUDA runtime files are complete.
11. Create the versioned `dist/HighlightMiner-v<version>-windows-x64.zip` archive.

Outputs for v0.1.2:

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
└── HighlightMiner-v0.1.2-windows-x64.zip
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

With no command-line arguments, a frozen HighlightMiner executable launches the Streamlit UI. The **Exit HighlightMiner** button shuts down the child Streamlit server and exits the application cleanly.

The packaged executable also retains CLI commands for diagnostics and automation:

```powershell
.\HighlightMiner.exe doctor
.\HighlightMiner.exe analyze "D:\VODs\stream.mp4" --chat "D:\VODs\stream - Chat.json"
.\HighlightMiner.exe ui
.\HighlightMiner.exe export ".\highlightminer_work\analysis.json"
```

## Why the launcher is different when frozen

In normal source mode, `sys.executable` is Python, so HighlightMiner can launch Streamlit with:

```text
python -m streamlit run ...
```

In a PyInstaller build, `sys.executable` is `HighlightMiner.exe`, not a Python interpreter. The frozen launcher therefore starts a second `HighlightMiner.exe` process in a private Streamlit-child mode. That child invokes Streamlit's CLI entry point inside the embedded Python runtime.

The raw `highlightminer/app.py` file is included as bundle data because Streamlit's `run` command expects an actual Python file path.

## Portable third-party runtimes

The repository does **not** commit FFmpeg, CUDA, or cuDNN binaries. The local build script only copies binaries that are already present on the build machine.

For the currently tested portable layout:

- FFmpeg / ffprobe: place them in the repository root or `./bin` before building.
- CUDA 12 / cuDNN 9: follow `CUDA_SETUP.md` and extract the DLLs into the repository root before building.

The resulting local ZIP will then carry those files beside `HighlightMiner.exe`.

## GitHub Actions build

`.github/workflows/build-windows-exe.yml` builds the frozen Windows application on a GitHub-hosted Windows runner and uploads a versioned workflow artifact using the same `HighlightMiner-v<version>-windows-x64` naming convention.

The workflow also verifies that the bundled raw Streamlit script exists, that CTranslate2 and faster-whisper import from the frozen executable, and that the packaged Streamlit server actually responds on localhost before the artifact is accepted.

For licensing/provenance clarity, the CI runner does not automatically download or redistribute external FFmpeg/CUDA/cuDNN binaries. The CI artifact therefore validates the frozen Python application itself; a fully self-contained local package is produced by running `build_windows.ps1` on a machine where the documented portable runtime files are already present.

## Current build toolchain

- Python 3.13 is used by the GitHub Actions packaging job.
- PyInstaller 6.21+ is declared in the `packaging` optional dependency group.
- Build mode: **onedir**, console enabled for early alpha diagnostics.
- Release archive target: **Windows x64**.

Once the portable build has been tested on clean Windows machines, the bundle can be reduced/optimized and an icon or console-less production launcher can be added without changing the analysis pipeline.
