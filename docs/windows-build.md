# Windows Build

This project can be packaged as a local Windows tray application with PyInstaller.

## Prerequisites

- Windows 10 or 11
- Python 3.11 or newer
- Project dependencies installed from the repository configuration:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

PyInstaller is a development/build dependency only. It is not required by DeskPilot at runtime.

## Build Command

From the repository root:

```powershell
.\scripts\build-windows.ps1
```

The script builds a PyInstaller `--onedir`, `--noconsole` distribution named `DeskPilot`.

## Output

The executable is created at:

```text
dist/DeskPilot/DeskPilot.exe
```

Run it from PowerShell or File Explorer:

```powershell
.\dist\DeskPilot\DeskPilot.exe
```

DeskPilot starts in the Windows system tray.

To enable optional OpenAI command transcription for the native tray app, set the environment variable before launching:

```powershell
$env:OPENAI_API_KEY = "your_api_key_here"
.\dist\DeskPilot\DeskPilot.exe
```

Do not commit or print real API keys.

## First-Run Behavior

User-created data is not bundled into the application. DeskPilot keeps settings, notes, and reminders under:

```text
~/Documents/DeskPilot/
```

The first use of wake-word detection may download/cache the local openWakeWord `hey_jarvis` model. If local transcription is used, the first real transcription may download/cache the local `tiny.en` faster-whisper model. These model caches are local machine state and are intentionally not committed or bundled from a developer workstation.

Native voice command transcription uses the local `voice_transcription_provider` setting:

- `auto`: use OpenAI `gpt-transcribe` when `OPENAI_API_KEY` exists, otherwise use local `faster-whisper`
- `local`: always use local `faster-whisper`
- `openai`: prefer OpenAI and fall back locally if cloud transcription is unavailable

DeskPilot sends only the already-recorded bounded command WAV after wake-word activation. It does not stream continuous microphone audio, does not attach notes/reminders/settings as context, and does not write or retain recordings.

## What Is Bundled

The build script packages the native tray app entrypoint and required Python dependencies for:

- PySide6 tray and overlay UI
- local microphone capture through `sounddevice`
- wake-word integration through `openwakeword`
- local transcription through `faster-whisper`
- optional OpenAI transcription through the official `openai` SDK
- local text-to-speech through `pyttsx3`

It does not bundle secrets, notes, reminders, settings, audio recordings, or local model cache directories.

## Troubleshooting

- If `PyInstaller is not installed`, run `python -m pip install -e ".[dev]"`.
- If wake-word startup fails on first run, start the app from PowerShell during troubleshooting so any logged traceback is visible.
- If OpenAI transcription does not run, confirm `OPENAI_API_KEY` is set in the same PowerShell session used to launch DeskPilot.
- If local transcription fails on first use, confirm the machine can download/cache the `tiny.en` model or that the model is already available in the local Hugging Face cache.
- If audio capture fails, check Windows microphone privacy permissions and the default recording device.
- If local TTS fails, verify Windows SAPI voices are available on the machine.
