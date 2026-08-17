param(
    [switch]$SkipTests,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$pyprojectPath = Join-Path $repoRoot "pyproject.toml"
$pyprojectText = Get-Content $pyprojectPath -Raw
if ($pyprojectText -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
    throw "Could not read project version from pyproject.toml."
}
$version = $Matches[1]

$hostArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($hostArchitecture -ne "X64") {
    throw "HighlightMiner Windows release packaging currently supports x64 only. Detected architecture: $hostArchitecture"
}

$packageName = "HighlightMiner-v$version-windows-x64"

Write-Host "HighlightMiner Windows build"
Write-Host "============================"
Write-Host "Version:      $version"
Write-Host "Architecture: windows-x64"
Write-Host ""

$buildVenv = Join-Path $repoRoot ".build-venv"
$buildPython = Join-Path $buildVenv "Scripts\python.exe"

if (-not (Test-Path $buildPython)) {
    Write-Host "Creating isolated build environment..."
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonCommand) { & python -m venv $buildVenv }
    elseif ($pyLauncher) { & py -3 -m venv $buildVenv }
    else { throw "Python 3.10+ was not found. Install Python first or put it on PATH." }
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the build virtual environment." }
}
else { Write-Host "Reusing existing .build-venv." }

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
if (-not (Test-Path $exePath)) { throw "Build completed without producing $exePath" }

Write-Host ""
Write-Host "Adding user-facing files..."
foreach ($name in @(
    "settings.json",
    "README.md",
    "V0.2_DEV.md",
    "RERUNS_AND_LEARNING.md",
    "SETTINGS.md",
    "BUILD_WINDOWS.md",
    "CUDA_SETUP.md",
    "ATTRIBUTIONS.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "LICENSE"
)) {
    $source = Join-Path $repoRoot $name
    if (Test-Path $source) { Copy-Item $source (Join-Path $distRoot $name) -Force }
}

$streamlitConfigSource = Join-Path $repoRoot ".streamlit"
$streamlitConfigDestination = Join-Path $distRoot ".streamlit"
if (Test-Path $streamlitConfigSource) {
    if (Test-Path $streamlitConfigDestination) { Remove-Item $streamlitConfigDestination -Recurse -Force }
    Copy-Item $streamlitConfigSource $streamlitConfigDestination -Recurse -Force
    Write-Host "Copied Streamlit theme configuration."
}

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

$cudaPatterns = @('^cublas.*\.dll$', '^cudnn.*\.dll$', '^nvrtc.*\.dll$', '^zlibwapi\.dll$')
$cudaFiles = Get-ChildItem -Path $repoRoot -File -Filter "*.dll" -ErrorAction SilentlyContinue | Where-Object {
    $name = $_.Name
    ($cudaPatterns | Where-Object { $name -match $_ }).Count -gt 0
}
foreach ($file in $cudaFiles) { Copy-Item $file.FullName (Join-Path $distRoot $file.Name) -Force }

$coreCuda = @("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")
$missingCoreCuda = @($coreCuda | Where-Object { -not (Test-Path (Join-Path $distRoot $_)) })
if ($missingCoreCuda.Count -gt 0) {
    Write-Warning ("Portable CUDA runtime is incomplete in the build: " + ($missingCoreCuda -join ", "))
}
else { Write-Host "Copied portable CUDA 12 / cuDNN 9 runtime DLLs." }

Write-Host ""
Write-Host "Smoke-testing executable entry point..."
& $exePath --help
if ($LASTEXITCODE -ne 0) { throw "HighlightMiner.exe failed its --help smoke test." }

Write-Host ""
Write-Host "Smoke-testing embedded desktop runtime imports..."
& $exePath __desktop_probe__
if ($LASTEXITCODE -ne 0) { throw "HighlightMiner.exe could not import the packaged pywebview/WebView2 backend." }

if ($ffmpegCopied -and $missingCoreCuda.Count -eq 0) {
    Write-Host ""
    Write-Host "Running packaged environment check..."
    & $exePath doctor
    if ($LASTEXITCODE -ne 0) { Write-Warning "The packaged doctor check reported a problem. Review the output above." }
}

$zipPath = Join-Path $repoRoot "dist\$packageName.zip"
$checksumPath = Join-Path $repoRoot "dist\SHA256SUMS.txt"
if (-not $SkipZip) {
    Write-Host ""
    Write-Host "Creating portable ZIP..."
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path $distRoot -DestinationPath $zipPath -CompressionLevel Optimal
    $hash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $packageName.zip" | Set-Content -Path $checksumPath -Encoding ascii
    Write-Host "SHA-256: $hash"
}

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "Executable folder: $distRoot"
if (-not $SkipZip) {
    Write-Host "Portable ZIP:      $zipPath"
    Write-Host "Checksum file:     $checksumPath"
}
Write-Host ""
Write-Host "Double-click HighlightMiner.exe to launch the embedded desktop UI."