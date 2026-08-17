param(
    [switch]$SkipTests,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

Write-Host "HighlightMiner Windows build"
Write-Host "============================"
Write-Host ""

$buildVenv = Join-Path $repoRoot ".build-venv"
$buildPython = Join-Path $buildVenv "Scripts\python.exe"

if (-not (Test-Path $buildPython)) {
    Write-Host "Creating isolated build environment..."

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue

    if ($pythonCommand) {
        & python -m venv $buildVenv
    }
    elseif ($pyLauncher) {
        & py -3 -m venv $buildVenv
    }
    else {
        throw "Python 3.10+ was not found. Install Python first or put it on PATH."
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the build virtual environment."
    }
}
else {
    Write-Host "Reusing existing .build-venv."
}

Write-Host "Updating build tooling..."
& $buildPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }

Write-Host "Installing HighlightMiner + build dependencies..."
& $buildPython -m pip install -e ".[dev,packaging]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

if (-not $SkipTests) {
    Write-Host ""
    Write-Host "Running tests..."
    & $buildPython -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; executable build aborted." }
}

Write-Host ""
Write-Host "Freezing HighlightMiner with PyInstaller..."
& $buildPython -m PyInstaller --noconfirm --clean HighlightMiner.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$distRoot = Join-Path $repoRoot "dist\HighlightMiner"
$exePath = Join-Path $distRoot "HighlightMiner.exe"
if (-not (Test-Path $exePath)) {
    throw "Build completed without producing $exePath"
}

Write-Host ""
Write-Host "Adding user-facing files..."
foreach ($name in @("settings.json", "README.md", "CUDA_SETUP.md", "ATTRIBUTIONS.md", "LICENSE")) {
    $source = Join-Path $repoRoot $name
    if (Test-Path $source) {
        Copy-Item $source (Join-Path $distRoot $name) -Force
    }
}

# Keep Streamlit's supported theme configuration beside the packaged app so
# source mode and the portable EXE use the same HighlightMiner appearance.
$streamlitConfigSource = Join-Path $repoRoot ".streamlit"
$streamlitConfigDestination = Join-Path $distRoot ".streamlit"
if (Test-Path $streamlitConfigSource) {
    if (Test-Path $streamlitConfigDestination) {
        Remove-Item $streamlitConfigDestination -Recurse -Force
    }
    Copy-Item $streamlitConfigSource $streamlitConfigDestination -Recurse -Force
    Write-Host "Copied Streamlit theme configuration."
}

# Copy FFmpeg/ffprobe from the same portable locations supported by the app.
$ffmpegCopied = $true
foreach ($name in @("ffmpeg.exe", "ffprobe.exe")) {
    $rootCandidate = Join-Path $repoRoot $name
    $binCandidate = Join-Path (Join-Path $repoRoot "bin") $name
    $destination = Join-Path $distRoot $name

    if (Test-Path $rootCandidate) {
        Copy-Item $rootCandidate $destination -Force
        Write-Host "Copied $name from repository root."
    }
    elseif (Test-Path $binCandidate) {
        Copy-Item $binCandidate $destination -Force
        Write-Host "Copied $name from .\bin."
    }
    else {
        $ffmpegCopied = $false
        Write-Warning "$name was not found locally; the EXE was built but this runtime was not added."
    }
}

# Copy locally supplied portable NVIDIA runtime files. These binaries are not
# committed to HighlightMiner; the build simply carries forward files the user
# already placed beside run.bat.
$cudaPatterns = @(
    '^cublas.*\.dll$',
    '^cudnn.*\.dll$',
    '^nvrtc.*\.dll$',
    '^zlibwapi\.dll$'
)
$cudaFiles = Get-ChildItem -Path $repoRoot -File -Filter "*.dll" -ErrorAction SilentlyContinue | Where-Object {
    $name = $_.Name
    ($cudaPatterns | Where-Object { $name -match $_ }).Count -gt 0
}

foreach ($file in $cudaFiles) {
    Copy-Item $file.FullName (Join-Path $distRoot $file.Name) -Force
}

$coreCuda = @("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")
$missingCoreCuda = @($coreCuda | Where-Object { -not (Test-Path (Join-Path $distRoot $_)) })
if ($missingCoreCuda.Count -gt 0) {
    Write-Warning ("Portable CUDA runtime is incomplete in the build: " + ($missingCoreCuda -join ", "))
}
else {
    Write-Host "Copied portable CUDA 12 / cuDNN 9 runtime DLLs."
}

Write-Host ""
Write-Host "Smoke-testing executable entry point..."
& $exePath --help
if ($LASTEXITCODE -ne 0) {
    throw "HighlightMiner.exe failed its --help smoke test."
}

if ($ffmpegCopied -and $missingCoreCuda.Count -eq 0) {
    Write-Host ""
    Write-Host "Running packaged environment check..."
    & $exePath doctor
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "The packaged doctor check reported a problem. Review the output above."
    }
}

$zipPath = Join-Path $repoRoot "dist\HighlightMiner-Windows-x64.zip"
if (-not $SkipZip) {
    Write-Host ""
    Write-Host "Creating portable ZIP..."
    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }
    Compress-Archive -Path $distRoot -DestinationPath $zipPath -CompressionLevel Optimal
}

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "Executable folder: $distRoot"
if (-not $SkipZip) {
    Write-Host "Portable ZIP:      $zipPath"
}
Write-Host ""
Write-Host "Double-click HighlightMiner.exe to launch the UI."