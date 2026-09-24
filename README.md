# DeskPilot

DeskPilot is a local-first Windows voice assistant that demonstrates safe native automation with deterministic command routing and explicit allowlisted actions.

## Features

- Native Windows tray shell with local wake-word activation: "Hey Jarvis"
- Push-to-talk browser demo and API endpoints for typed, uploaded-audio, and microphone commands
- Configurable command transcription: automatic OpenAI `gpt-transcribe` when `OPENAI_API_KEY` is set, or local `faster-whisper` fallback
- Optional OpenAI natural-language command understanding for unsupported phrasing, with strict function schemas and local allowlist validation
- Local Windows SAPI text-to-speech through `pyttsx3`
- Deterministic English command router remains the first path for every command
- Strict allowlisted execution for apps, fixed websites, bounded search, media keys, workspace shortcuts, notes, reminders, and settings
- Local notes, reminders, and settings stored under `~/Documents/DeskPilot`
- Unit-tested services with mocked microphone, speech, wake word, process launching, and timers

## Privacy And Safety

DeskPilot is designed to keep actions, storage, wake-word detection, text-to-speech, notes, reminders, and settings local. Audio is captured only after an explicit button press or enabled local wake-word detection.

Native wake-word commands can optionally use OpenAI `gpt-transcribe` for the already-recorded short command WAV. DeskPilot can also optionally use OpenAI Responses function calling to interpret natural English phrasing only after the deterministic router does not recognize a command. DeskPilot never streams continuous microphone audio, does not send notes/reminders/settings/history/file contents as context, and does not write or retain command recordings or cloud requests.

Cloud interpretation never executes actions. It may only propose a strict typed outcome, and local DeskPilot code validates that outcome through the existing command router and allowlisted executor. If OpenAI transcription or interpretation is unavailable, DeskPilot falls back to local behavior when possible.

Safety is enforced with deterministic parsing and explicit allowlists. DeskPilot does not execute arbitrary text, shell commands, paths, URLs, or user-provided executables. Search queries are URL-encoded into trusted search endpoints, and custom aliases may only point to already-supported fixed commands.

See [SECURITY.md](SECURITY.md) for the safety model and disclosure guidance.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Run the API:

```powershell
python -m uvicorn deskpilot_backend.main:app --reload
```

Then visit `http://127.0.0.1:8000/api/v1/health`.

Run the native tray shell:

```powershell
python -m deskpilot_backend.desktop
```

DeskPilot starts in the Windows system tray. Use the tray menu to start or stop wake-word listening, show or hide the overlay, or quit.

## Browser Demo

With the API running, open `http://127.0.0.1:8000`, click `Talk (4 seconds)`, and say "open calculator". The browser calls the existing local microphone command endpoint.

## Native Voice Demo

Start the tray app, choose `Start wake word listening`, say "Hey Jarvis", then speak a supported command while the cyan listening border is visible. DeskPilot plays a short local Windows cue when command recording begins, stops the wake-word microphone stream, records one local command, transcribes it locally, runs the allowlisted assistant flow, narrates the response with local TTS, hides the border, and resumes wake-word listening if it is still enabled.

Native voice states:

- Cyan: listening for the command
- Amber: processing transcription and the allowlisted action
- Green: completed successfully, then hides
- Red: recoverable error or unknown command, then hides

The first wake-word start may download/cache openWakeWord's local `hey_jarvis` model. openWakeWord code is Apache-2.0 licensed, while its included pre-trained models are licensed CC BY-NC-SA 4.0.

For stronger native command transcription, set `OPENAI_API_KEY` before starting the tray app:

```powershell
$env:OPENAI_API_KEY = "your_api_key_here"
python -m deskpilot_backend.desktop
```

Do not commit API keys. With the default `auto` providers, DeskPilot uses OpenAI only when this environment variable exists; otherwise it preserves local transcription and deterministic command routing. OpenAI usage may incur API cost.

## Tests

```powershell
python -m pytest
python -m compileall src
```

## Documentation

- [Architecture](docs/architecture.md)
- [90-second demo script](docs/demo-script.md)
- [Windows build](docs/windows-build.md)
- [Security](SECURITY.md)

## Local Settings

DeskPilot stores local preferences in `~/Documents/DeskPilot/settings.json`. The file is created only when missing, using this schema:

```json
{
  "version": 1,
  "command_capture_duration_seconds": 4,
  "recording_start_cue_enabled": true,
  "wake_listening_on_startup": false,
  "voice_transcription_provider": "auto",
  "voice_command_interpreter_provider": "auto",
  "custom_aliases": {}
}
```

`command_capture_duration_seconds` is allowed from `2` through `8`; invalid values fall back to `4`. `recording_start_cue_enabled` controls the local Windows cue before native command recording. `wake_listening_on_startup` starts wake-word listening when the tray shell opens.

`voice_transcription_provider` controls only native wake-word command transcription:

- `auto`: use OpenAI `gpt-transcribe` when `OPENAI_API_KEY` exists, otherwise use local `faster-whisper`
- `local`: always use local `faster-whisper`
- `openai`: prefer OpenAI and fall back locally if cloud transcription is unavailable

Invalid provider values use `auto`.

`voice_command_interpreter_provider` controls natural-language command understanding after deterministic routing fails:

- `auto`: use OpenAI Responses function calling when `OPENAI_API_KEY` exists, otherwise deterministic-only behavior
- `local`: deterministic-only behavior
- `openai`: prefer OpenAI interpretation and show a recoverable message if no key is configured

The interpreter uses `store=false`, strict function schemas, no OpenAI built-in tools, and one tool call. Returned tool arguments are validated locally before any action can run.

Custom aliases map one fixed phrase to an existing fixed command ID:

```json
{
  "custom_aliases": {
    "open my projects": "open github"
  }
}
```

Aliases cannot replace built-in commands, collide after normalization, or point to executables, paths, URLs, shell commands, media controls, notes, reminders, or parameterized searches. Invalid settings are not rewritten; DeskPilot uses safe defaults and shows a local warning.

## API Endpoints

- `GET /api/v1/health`
- `POST /api/v1/commands`
- `POST /api/v1/actions/execute`
- `POST /api/v1/assistant/commands`
- `POST /api/v1/speech/speak`
- `POST /api/v1/transcriptions`
- `POST /api/v1/voice/commands`
- `POST /api/v1/microphone/commands`

## Supported Commands

Application commands:

- `open calculator`
- `open notepad`
- `open file explorer`
- `open explorer`
- `open settings`
- `open browser`
- `open task manager`

Settings commands:

- `open deskpilot settings`

Fixed-site commands:

- `open google`
- `open youtube`
- `open github`

Search commands:

- `search web for deskpilot`
- `search google for python url encoding`
- `search youtube for local voice assistant`
- `search github for fastapi examples`

Notes commands:

- `take a note remember this`
- `note remember this`
- `read latest note`
- `how many notes do I have`
- `open notes folder`

Reminder commands:

- `remind me in one minute to stretch`
- `remind me in 10 minutes to stretch`
- `remind me in twenty five minutes to stretch`
- `list reminders`
- `what are my reminders`

Workspace shortcuts:

- `open downloads`
- `open documents`
- `open desktop`

Information commands:

- `what time is it`
- `what's the time`
- `what is the date`
- `what's today's date`
- `battery status`
- `what is my battery level`
- `memory status`
- `how much memory am I using`
- `disk space`
- `how much disk space do I have`
- `help`
- `what can you do`

Cancel commands:

- `cancel`
- `never mind`

Volume commands:

- `volume up`
- `turn volume up`
- `volume down`
- `turn volume down`
- `mute`
- `mute volume`

Media commands:

- `play music`
- `pause music`
- `next song`
- `next track`
- `previous song`
- `previous track`

Media controls use fixed Windows virtual media keys and affect the active Windows media session. Workspace shortcuts use fixed Windows targets only. Folder shortcuts are derived from known local user directories; DeskPilot never accepts spoken paths. System status commands are read-only and use standard-library or Windows `ctypes` calls.

Fixed-site commands use exact allowlisted HTTPS URLs. Search commands encode the query into the trusted search site's `q` parameter and open the results in the default browser; DeskPilot does not make direct HTTP requests.

Notes are saved as UTF-8 `.txt` files under `~/Documents/DeskPilot/notes`. Reminders are saved locally in `~/Documents/DeskPilot/reminders.json`, reloaded on startup, and scheduled from saved due times. When a reminder is due, DeskPilot shows a native tray notification and says `Reminder: <text>` with local TTS.
