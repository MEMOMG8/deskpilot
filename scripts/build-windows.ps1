param(
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_-]{0,70}$')]
    [string]$BuildId = ("dp032-test-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $RepoRoot "dist\$BuildId"
$WorkDir = Join-Path $RepoRoot "build\$BuildId"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Install project build dependencies in .venv first: python -m pip install -e `".[dev]`""
}
if ((Test-Path -LiteralPath $OutputDir) -or (Test-Path -LiteralPath $WorkDir)) {
    throw "BuildId already exists. Choose a new BuildId; previous artifacts are never deleted."
}
New-Item -ItemType Directory -Path $OutputDir, $WorkDir | Out-Null
$SavedBuildEnvironment = @{}
$BuildEnvironmentNames = @(
    "PATH", "PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"
)
foreach ($EnvironmentName in $BuildEnvironmentNames) {
    $SavedBuildEnvironment[$EnvironmentName] = [Environment]::GetEnvironmentVariable($EnvironmentName, "Process")
}

Push-Location $RepoRoot
try {
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Project dependency check failed." }
    $BuildLog = Join-Path $WorkDir "pyinstaller.log"
    # Prevent DLLs from unrelated tools on the developer PATH entering the bundle.
    foreach ($EnvironmentName in $BuildEnvironmentNames) {
        [Environment]::SetEnvironmentVariable($EnvironmentName, $null, "Process")
    }
    $env:PATH = (Join-Path $RepoRoot ".venv\Scripts") + ";" +
        (Join-Path $env:SystemRoot "System32") + ";" + $env:SystemRoot
    $ErrorActionPreference = "Continue"
    & $Python -m PyInstaller --noconfirm --clean `
        --distpath $OutputDir --workpath $WorkDir `
        (Join-Path $RepoRoot "packaging\DeskPilot.spec") 2>&1 |
        Tee-Object -FilePath $BuildLog
    $BuildExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    foreach ($EnvironmentName in $BuildEnvironmentNames) {
        [Environment]::SetEnvironmentVariable($EnvironmentName, $SavedBuildEnvironment[$EnvironmentName], "Process")
    }
    if ($BuildExitCode -ne 0) { throw "PyInstaller failed. See $BuildLog" }
    $PackageDir = Join-Path $OutputDir "DeskPilot"
    if (-not (Test-Path -LiteralPath (Join-Path $PackageDir "DeskPilot.exe"))) {
        throw "PyInstaller did not produce DeskPilot.exe."
    }
    & $Python (Join-Path $RepoRoot "scripts\package-windows.py") `
        --package $PackageDir --build-id $BuildId
    if ($LASTEXITCODE -ne 0) { throw "Packaged checks or archive creation failed. See $OutputDir" }
    Write-Host "Test distribution ready: $OutputDir"
}
finally {
    $ErrorActionPreference = "Stop"
    foreach ($EnvironmentName in $BuildEnvironmentNames) {
        [Environment]::SetEnvironmentVariable($EnvironmentName, $SavedBuildEnvironment[$EnvironmentName], "Process")
    }
    Pop-Location
}
