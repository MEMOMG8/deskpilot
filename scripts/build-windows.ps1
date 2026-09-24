$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$DistDir = Join-Path $RepoRoot "dist"
$BuildDir = Join-Path $RepoRoot "build"
$EntryDir = Join-Path $BuildDir "pyinstaller-entry"
$EntryScript = Join-Path $EntryDir "deskpilot_desktop_entry.py"
$ExePath = Join-Path $DistDir "DeskPilot\DeskPilot.exe"

Push-Location $RepoRoot
try {
    & $Python -c "import PyInstaller" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed. Run: python -m pip install -e `".[dev]`""
    }

    Remove-Item -LiteralPath (Join-Path $DistDir "DeskPilot") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $BuildDir "DeskPilot") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $EntryDir -Recurse -Force -ErrorAction SilentlyContinue

    New-Item -ItemType Directory -Force $EntryDir | Out-Null
    Set-Content -LiteralPath $EntryScript -Encoding UTF8 -Value @"
from deskpilot_backend.desktop import main

raise SystemExit(main())
"@

    $PyInstallerArgs = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--noconsole",
        "--name", "DeskPilot",
        "--paths", (Join-Path $RepoRoot "src"),
        "--distpath", $DistDir,
        "--workpath", $BuildDir,
        "--specpath", $BuildDir,
        "--collect-all", "pyttsx3",
        "--collect-all", "sounddevice",
        "--collect-all", "openwakeword",
        "--collect-all", "faster_whisper",
        "--collect-all", "openai",
        "--collect-all", "ctranslate2",
        "--collect-all", "av",
        "--collect-all", "onnxruntime",
        "--copy-metadata", "openwakeword",
        "--copy-metadata", "faster-whisper",
        "--copy-metadata", "openai",
        "--copy-metadata", "pyttsx3",
        "--copy-metadata", "sounddevice",
        "--hidden-import", "deskpilot_backend.desktop",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "pyttsx3.drivers",
        "--hidden-import", "pyttsx3.drivers.sapi5",
        "--hidden-import", "pythoncom",
        "--hidden-import", "pywintypes",
        "--hidden-import", "win32com.client",
        $EntryScript
    )

    & $Python $PyInstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    if (-not (Test-Path $ExePath)) {
        throw "Expected executable was not created: $ExePath"
    }

    Write-Host "Built DeskPilot: $ExePath"
}
finally {
    Pop-Location
}
