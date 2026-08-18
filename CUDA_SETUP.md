# Portable NVIDIA CUDA runtime setup — Windows

HighlightMiner uses `faster-whisper` / CTranslate2 for GPU transcription. Current faster-whisper releases require **cuBLAS for CUDA 12** and **cuDNN 9 for CUDA 12** when using recent CTranslate2 versions.

For source/development checkouts, portable NVIDIA DLLs should live in the dedicated `runtime\cuda` directory. Packaged Windows builds still place the allowlisted DLLs directly beside `HighlightMiner.exe`, where the frozen runtime expects them. A system-wide CUDA Toolkit installation is not required for this layout.

## 1. Download the CUDA 12 + cuDNN 9 library bundle

faster-whisper's upstream documentation points Windows users to the NVIDIA library archive published with Purfview's `whisper-standalone-win` project.

Recommended current Windows bundle:

**`cuBLAS.and.cuDNN_CUDA12_win_v3.7z`**

Direct download:

https://github.com/Purfview/whisper-standalone-win/releases/download/libs/cuBLAS.and.cuDNN_CUDA12_win_v3.7z

Release page / alternate bundles:

https://github.com/Purfview/whisper-standalone-win/releases/tag/libs

Upstream faster-whisper GPU requirements:

https://github.com/SYSTRAN/faster-whisper#gpu

The v3 bundle contains CUDA 12 cuBLAS and cuDNN 9 libraries. Do **not** use the CUDA 11 archive with the current default HighlightMiner/CTranslate2 stack.

## 2. Extract the archive into `runtime\cuda`

### Source / development checkout

Create `runtime\cuda` under the repository root and extract the **contents** of the `.7z` archive there:

```text
HighlightMiner/
├── runtime/
│   └── cuda/
│       ├── cublas64_12.dll
│       ├── cublasLt64_12.dll
│       ├── cudnn64_9.dll
│       └── cudnn_*.dll
├── ffmpeg.exe                  # optional portable FFmpeg layout
├── ffprobe.exe
├── run.bat
├── setup.ps1
├── settings.json
├── highlightminer/
└── .venv/
```

Source mode prefers `runtime\cuda` when its core CUDA/cuDNN files are present. The older root-folder DLL layout remains a backward-compatible source fallback, but the Windows packager no longer sweeps DLLs from the repository root.

### Packaged Windows application

For a PyInstaller build, the allowlisted DLLs are copied directly beside the executable:

```text
HighlightMiner/
├── HighlightMiner.exe
├── cublas64_12.dll
├── cublasLt64_12.dll
├── cudnn64_9.dll
├── cudnn_*.dll
├── ffmpeg.exe
├── ffprobe.exe
├── settings.json
└── _internal/
```

`build_windows.ps1` copies only this CUDA 12 / cuDNN 9 allowlist from `runtime\cuda`:

```text
cublas64_12.dll
cublasLt64_12.dll
cudnn64_9.dll
cudnn_adv64_9.dll
cudnn_cnn64_9.dll
cudnn_engines_precompiled64_9.dll
cudnn_engines_runtime_compiled64_9.dll
cudnn_graph64_9.dll
cudnn_heuristic64_9.dll
cudnn_ops64_9.dll
```

`zlibwapi.dll` is optional and is copied from the same directory when present. Other DLL names are ignored by the packager.

## 3. Verify the runtime

Source checkout:

```powershell
.\.venv\Scripts\python.exe -m highlightminer doctor
```

Packaged application:

```powershell
.\HighlightMiner.exe doctor
```

A healthy source setup using the dedicated directory should include lines similar to:

```text
Portable CUDA DLL root: C:\path\to\HighlightMiner\runtime\cuda
  cublas64_12.dll: yes
  cublasLt64_12.dll: yes
  cudnn64_9.dll: yes
CUDA devices visible to CTranslate2: 1
GPU Whisper runtime: core CUDA/cuDNN DLLs loadable
```

A packaged build reports the application folder instead because its copied runtime DLLs sit beside `HighlightMiner.exe`.

If a DLL exists but one of its dependencies cannot be loaded, `doctor` reports that instead of incorrectly claiming the GPU runtime is ready.

## Why these DLLs are not committed to HighlightMiner

The CUDA/cuDNN runtime binaries are third-party NVIDIA software. HighlightMiner does not vendor or redistribute them through the source repository. Users obtain them from the upstream bundle, and local runtime DLLs are ignored by Git. The Windows build script copies only explicitly allowlisted runtime files already present on the build machine.

## Credits

- **NVIDIA** — CUDA, cuBLAS, and cuDNN.
- **Purfview / whisper-standalone-win** — publishes the convenient Windows cuBLAS + cuDNN archive referenced by faster-whisper's own setup documentation.
- **SYSTRAN faster-whisper / OpenNMT CTranslate2** — GPU transcription stack used by HighlightMiner.

Each third-party component remains subject to its own upstream license and terms.
