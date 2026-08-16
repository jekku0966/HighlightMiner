$ErrorActionPreference = "Stop"

# Always operate from the repository directory, even if setup.ps1 was launched elsewhere.
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

Write-Host "HighlightMiner setup"
Write-Host "===================="
Write-Host ""

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
    $versionOk = & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
} else {
    $versionText = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    $versionOk = & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
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
Write-Host "Running environment check..."
Write-Host ""

# doctor knows how to find ffmpeg/ffprobe in ./bin, the repo root, or system PATH.
& $venvPython -m highlightminer doctor
$doctorExit = $LASTEXITCODE

Write-Host ""
if ($doctorExit -eq 0) {
    Write-Host "Environment check passed." -ForegroundColor Green
} else {
    Write-Host "Environment check needs attention." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "FFmpeg / ffprobe can be provided in any of these locations:"
    Write-Host "  1. .\bin\ffmpeg.exe and .\bin\ffprobe.exe"
    Write-Host "  2. .\ffmpeg.exe and .\ffprobe.exe (beside run.bat)"
    Write-Host "  3. system PATH"
    Write-Host ""
    Write-Host "See README.md for tested FFmpeg builds, CUDA/faster-whisper notes, and troubleshooting."
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
