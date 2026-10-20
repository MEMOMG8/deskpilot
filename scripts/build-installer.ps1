param(
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_-]{0,70}$')]
    [string]$BuildId = ("dp033-test-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Prepare the project .venv first." }
& (Join-Path $PSScriptRoot "get-inno-setup.ps1")
& (Join-Path $PSScriptRoot "build-windows.ps1") -BuildId $BuildId
& $Python -B (Join-Path $PSScriptRoot "build-installer.py") --build-id $BuildId
if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }
