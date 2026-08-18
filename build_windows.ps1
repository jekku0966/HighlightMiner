param(
    [switch]$SkipTests,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$hostArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($hostArchitecture -ne "X64") {
    throw "HighlightMiner Windows release packaging currently supports x64 only. Detected architecture: $hostArchitecture"
}

function Get-PythonVersionInfo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    try {
        $versionOutput = & $Executable @Arguments --version 2>&1
    }
    catch {
        return $null
    }

    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    $versionMatch = [regex]::Match(($versionOutput -join " "), 'Python\s+(\d+)\.(\d+)(?:\.(\d+))?')
    if (-not $versionMatch.Success) {
        return $null
    }

    return [PSCustomObject]@{
        Major = [int]$versionMatch.Groups[1].Value
        Minor = [int]$versionMatch.Groups[2].Value
        Label = "$($versionMatch.Groups[1].Value).$($versionMatch.Groups[2].Value)"
    }
}

function Test-CompatiblePython {
    param($VersionInfo)

    return $null -ne $VersionInfo -and (
        $VersionInfo.Major -gt 3 -or
        ($VersionInfo.Major -eq 3 -and $VersionInfo.Minor -ge 10)
    )
}

$buildVenv = Join-Path $repoRoot ".build-venv"
$buildPython = Join-Path $buildVenv "Scripts\python.exe"

if (Test-Path $buildPython) {
    $existingVersion = Get-PythonVersionInfo -Executable $buildPython
    if (-not (Test-CompatiblePython $existingVersion)) {
        Write-Host "Existing build environment has an unsupported or unreadable Python version. Recreating..."
        Remove-Item $buildVenv -Recurse -Force
    }
    else {
        Write-Host "Reusing .build-venv with Python $($existingVersion.Label)."
    }
}

if (-not (Test-Path $buildPython)) {
    Write-Host "Creating isolated build environment..."

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pythonExecutable = $null
    $pythonArguments = @()
    $selectedVersion = $null

    if ($pyLauncher) {
        $launcherVersion = Get-PythonVersionInfo -Executable $pyLauncher.Source -Arguments @("-3")
        if (Test-CompatiblePython $launcherVersion) {
            $pythonExecutable = $pyLauncher.Source
            $pythonArguments = @("-3")
            $selectedVersion = $launcherVersion
        }
    }

    if (-not $pythonExecutable -and $pythonCommand) {
        $pathVersion = Get-PythonVersionInfo -Executable $pythonCommand.Source
        if (Test-CompatiblePython $pathVersion) {
            $pythonExecutable = $pythonCommand.Source
            $selectedVersion = $pathVersion
        }
    }

    if (-not $pythonExecutable) {
        throw "Python 3.10 or newer is required. Install it or expose it through the 'py' launcher or PATH."
    }

    Write-Host "Creating the build environment with Python $($selectedVersion.Label)..."
    & $pythonExecutable @pythonArguments -m venv $buildVenv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $buildPython)) {
        throw "Failed to create the build virtual environment."
    }
}

Write-Host "Updating build tooling..."
& $buildPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }

Write-Host "Installing HighlightMiner + build dependencies..."
& $buildPython -m pip install -e ".[dev,packaging]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

$versionScript = Join-Path $repoRoot "tools\project_version.py"
$versionOutput = & $buildPython $versionScript
if ($LASTEXITCODE -ne 0 -or -not $versionOutput) {
    throw "Could not read project.version through tools/project_version.py."
}
$version = ($versionOutput -join "").Trim()
$packageName = "HighlightMiner-v$version-windows-x64"

Write-Host ""
Write-Host "HighlightMiner Windows build"
Write-Host "============================"
Write-Host "Version:      $version"
Write-Host "Architecture: windows-x64"
Write-Host ""

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
    "LEARNING.md",
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

$cudaRuntimeRoot = Join-Path $repoRoot "runtime\cuda"
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

foreach ($name in @($requiredCudaDlls + $optionalCudaDlls)) {
    $source = Join-Path $cudaRuntimeRoot $name
    if (Test-Path $source) {
        Copy-Item $source (Join-Path $distRoot $name) -Force
    }
}

$missingRequiredCuda = @($requiredCudaDlls | Where-Object { -not (Test-Path (Join-Path $distRoot $_)) })
if ($missingRequiredCuda.Count -gt 0) {
    Write-Warning ("Portable CUDA runtime was not fully added from runtime\cuda: " + ($missingRequiredCuda -join ", "))
    Write-Warning "The packaged app still supports CPU and a compatible system CUDA installation."
}
else { Write-Host "Copied portable CUDA 12 / cuDNN 9 runtime DLLs from runtime\cuda." }

Write-Host ""
Write-Host "Smoke-testing executable entry point..."
& $exePath --help
if ($LASTEXITCODE -ne 0) { throw "HighlightMiner.exe failed its --help smoke test." }

Write-Host ""
Write-Host "Smoke-testing embedded desktop runtime imports..."
& $exePath __desktop_probe__
if ($LASTEXITCODE -ne 0) { throw "HighlightMiner.exe could not import the packaged pywebview/WebView2 backend." }

if ($ffmpegCopied -and $missingRequiredCuda.Count -eq 0) {
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
