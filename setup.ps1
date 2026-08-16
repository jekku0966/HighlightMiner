$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.10+ first."
}

$python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
if ($python -eq "py") {
    & py -3 -m venv .venv
} else {
    & python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .
Write-Host ""
Write-Host "Installed. Now run: .\\run.bat"
Write-Host "You also need ffmpeg and ffprobe available on PATH."
