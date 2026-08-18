$ErrorActionPreference = "Stop"

# Always operate from the repository directory, even if setup.ps1 was launched elsewhere.
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

Write-Host "HighlightMiner setup"
Write-Host "===================="
Write-Host ""

# Keep optional portable runtimes in predictable locations. These directories are
# also tracked with .gitkeep files, but setup recreates them if they were removed.
$binRoot = Join-Path $repoRoot "bin"
$cudaRuntimeRoot = Join-Path $repoRoot "runtime\cuda"
foreach ($directory in @($binRoot, $cudaRuntimeRoot)) {
    if (-not (Test-Path $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        Write-Host "Created $directory"
    }
}

$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue

if (-not $pyLauncher -and -not $pythonCommand) {
    throw "Python was not found. Install Python 3.10+ first."
}

# Prefer the Windows Python launcher when available; otherwise use python from PATH.
if ($pyLauncher) {
    $basePython = @("py", "-3")
} else {
    $basePython = @("python")
}

# Check that the selected interpreter is Python 3.10 or newer.
if ($basePython[0] -eq "py") {
    $versionText = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
} else {
    $versionText = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
}

if ($LASTEXITCODE -ne 0) {
    throw "HighlightMiner requires Python 3.10+. Selected interpreter: Python $versionText"
}

Write-Host "Python: $versionText"
Write-Host ""

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..."
    if ($basePython[0] -eq "py") {
        & py -3 -m venv .venv
    } else {
        & python -m venv .venv
    }
} else {
    Write-Host "Existing .venv found; reusing it."
}

Write-Host "Updating pip..."
& $venvPython -m pip install --upgrade pip

Write-Host "Installing HighlightMiner..."
& $venvPython -m pip install -e .

Write-Host ""
Write-Host "Portable NVIDIA CUDA runtime check"
Write-Host "----------------------------------"

$requiredCudaDlls = @(
    "cublas64_12.dll",
    "cublasLt64_12.dll",
    "cudnn64_9.dll",
    "cudnn_adv64_9.dll",
    "cudnn_cnn64_9.dll",
    "cudnn_engines_precompiled64_9.dll",
    "cudnn_engines_runtime_compiled64_9.dll",
    "cudnn_graph64_9.dll",
    "cudnn_heuristic64_9.dll",
    "cudnn_ops64_9.dll"
)
$optionalCudaDlls = @("zlibwapi.dll")
$coreCudaDlls = @("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")

# v0.1/v0.2-dev originally documented CUDA DLLs beside run.bat. Preserve that
# setup automatically by copying only known runtime filenames into runtime\cuda.
$migratedCudaDlls = @()
foreach ($name in @($requiredCudaDlls + $optionalCudaDlls)) {
    $legacySource = Join-Path $repoRoot $name
    $destination = Join-Path $cudaRuntimeRoot $name
    if ((Test-Path $legacySource) -and -not (Test-Path $destination)) {
        Copy-Item $legacySource $destination -Force
        $migratedCudaDlls += $name
    }
}
if ($migratedCudaDlls.Count -gt 0) {
    Write-Host "Copied existing root-folder CUDA runtime files into .\runtime\cuda:" -ForegroundColor Green
    Write-Host "  $($migratedCudaDlls -join ', ')"
}

$missingCudaDlls = @($coreCudaDlls | Where-Object { -not (Test-Path (Join-Path $cudaRuntimeRoot $_)) })

if ($missingCudaDlls.Count -gt 0) {
    Write-Host "GPU transcription DLLs are not fully present in .\runtime\cuda." -ForegroundColor Yellow
    Write-Host "Missing core files: $($missingCudaDlls -join ', ')"
    Write-Host ""
    Write-Host "For NVIDIA GPU transcription, download:"
    Write-Host "  https://github.com/Purfview/whisper-standalone-win/releases/download/libs/cuBLAS.and.cuDNN_CUDA12_win_v3.7z"
    Write-Host ""
    Write-Host "Extract the CONTENTS of that archive into the directory setup already created:"
    Write-Host "  $cudaRuntimeRoot"
    Write-Host ""
    Write-Host "See CUDA_SETUP.md for the portable Windows layout."
} else {
    Write-Host "Core CUDA 12 / cuDNN 9 DLLs found in .\runtime\cuda." -ForegroundColor Green
}

Write-Host ""
Write-Host "Running environment check..."
Write-Host ""

# doctor knows how to find ffmpeg/ffprobe in ./bin, the repo root, or system PATH,
# and prefers the portable CUDA/cuDNN DLLs stored in ./runtime/cuda.
& $venvPython -m highlightminer doctor
$doctorExit = $LASTEXITCODE

Write-Host ""
if ($doctorExit -eq 0) {
    Write-Host "Environment check passed." -ForegroundColor Green
} else {
    Write-Host "Environment check needs attention." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "FFmpeg / ffprobe can be provided in any of these locations:"
    Write-Host "  1. .\bin\ffmpeg.exe and .\bin\ffprobe.exe (bin is created automatically)"
    Write-Host "  2. .\ffmpeg.exe and .\ffprobe.exe (beside run.bat)"
    Write-Host "  3. system PATH"
    Write-Host ""
    Write-Host "For NVIDIA GPU transcription, place CUDA 12/cuDNN 9 DLLs in .\runtime\cuda."
    Write-Host "See CUDA_SETUP.md and README.md for setup details."
}

Write-Host ""
Write-Host "Twitch input recommendation:"
Write-Host "  Use TwitchDownloader to download the VOD and its matching JSON chat export."
Write-Host "  https://github.com/lay295/TwitchDownloader/releases"
Write-Host "  TwitchDownloader is optional and is not bundled with HighlightMiner."

Write-Host ""
Write-Host "Setup complete."
Write-Host "Launch HighlightMiner with: .\run.bat"
Write-Host "Re-run diagnostics any time with: .\.venv\Scripts\python.exe -m highlightminer doctor"
