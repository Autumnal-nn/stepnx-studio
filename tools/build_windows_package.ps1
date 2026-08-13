param(
    [string]$Python = "py",
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$DistRoot = Join-Path $RepositoryRoot "dist"
$BundleName = "StepNX-Studio-Windows"
$BundlePath = Join-Path $DistRoot $BundleName
$ArchivePath = Join-Path $DistRoot "$BundleName.zip"

Push-Location $RepositoryRoot
try {
    if (-not $SkipInstall) {
        & $Python -m pip install --upgrade pip
        & $Python -m pip install -e ".[gui,build]"
    }

    if (-not $SkipTests) {
        $env:QT_QPA_PLATFORM = "offscreen"
        & $Python tools/run_windows_test_gate.py
        if ($LASTEXITCODE -ne 0) {
            throw "The Windows test gate failed with exit code $LASTEXITCODE"
        }
    }

    & $Python -m PyInstaller --noconfirm --clean packaging/stepnx-studio.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    if (-not (Test-Path (Join-Path $BundlePath "StepNX-Studio.exe"))) {
        throw "The expected StepNX-Studio.exe was not produced"
    }

    if (Test-Path $ArchivePath) {
        Remove-Item $ArchivePath -Force
    }
    Compress-Archive -Path $BundlePath -DestinationPath $ArchivePath -CompressionLevel Optimal

    $Hash = Get-FileHash $ArchivePath -Algorithm SHA256
    Write-Host "Windows package: $ArchivePath"
    Write-Host "SHA-256: $($Hash.Hash.ToLowerInvariant())"
}
finally {
    Pop-Location
}
