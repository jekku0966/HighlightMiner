# Portable NVIDIA CUDA runtime setup — Windows

HighlightMiner uses `faster-whisper` / CTranslate2 for GPU transcription. Current faster-whisper releases require **cuBLAS for CUDA 12** and **cuDNN 9 for CUDA 12** when using recent CTranslate2 versions.

HighlightMiner supports a portable Windows layout: the required runtime DLLs can live directly in the repository root beside `run.bat`. A system-wide CUDA Toolkit installation is not required for this layout.

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

## 2. Extract the archive directly into the HighlightMiner root

Extract the **contents** of the `.7z` archive into the same directory that contains `run.bat`.

The important part is that files such as these are directly in the project root:

```text
HighlightMiner/
├── cublas64_12.dll
├── cublasLt64_12.dll
├── cudnn64_9.dll
├── cudnn_*.dll                 # additional cuDNN DLLs from the same archive
├── ffmpeg.exe                  # optional portable FFmpeg layout
├── ffprobe.exe
├── run.bat
├── setup.ps1
├── settings.json
├── highlightminer/
└── .venv/
```

Do **not** leave them nested like this:

```text
HighlightMiner/
└── cuBLAS.and.cuDNN_CUDA12_win_v3/
    └── cublas64_12.dll
```

HighlightMiner explicitly adds its repository root to the Windows DLL search path before importing CTranslate2/faster-whisper, so the root-folder layout is intentional.

## 3. Verify the runtime

After extracting the DLLs, run:

```powershell
.\.venv\Scripts\python.exe -m highlightminer doctor
```

A healthy NVIDIA setup should include lines similar to:

```text
Portable CUDA DLL root: C:\path\to\HighlightMiner
  cublas64_12.dll: yes
  cublasLt64_12.dll: yes
  cudnn64_9.dll: yes
CUDA devices visible to CTranslate2: 1
GPU Whisper runtime: core CUDA/cuDNN DLLs loadable
```

If a DLL exists but one of its dependencies cannot be loaded, `doctor` reports that instead of incorrectly claiming the GPU runtime is ready.

## Why these DLLs are not committed to HighlightMiner

The CUDA/cuDNN runtime binaries are third-party NVIDIA software. HighlightMiner does not vendor or redistribute them. Users download them from the upstream bundle and the local DLL files are ignored by Git.

## Credits

- **NVIDIA** — CUDA, cuBLAS, and cuDNN.
- **Purfview / whisper-standalone-win** — publishes the convenient Windows cuBLAS + cuDNN archive referenced by faster-whisper's own setup documentation.
- **SYSTRAN faster-whisper / OpenNMT CTranslate2** — GPU transcription stack used by HighlightMiner.

Each third-party component remains subject to its own upstream license and terms.
