# DeskPilot

DeskPilot is a local-first Windows desktop voice assistant portfolio project. This milestone contains a minimal Python backend with a deterministic typed-command router, safe calculator execution, assistant orchestration, local text-to-speech, offline file transcription, explicit local microphone commands, and a native Windows tray shell.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

The install includes `pyttsx3`, which uses the local Windows SAPI voice for text-to-speech, `faster-whisper` and `python-multipart` for offline audio-file transcription, `sounddevice` for explicit local microphone capture, `PySide6` for the native Windows tray shell, and `openwakeword` for local wake-word detection.

## Run Tests

```powershell
python -m pytest
```

## Run The API

```powershell
python -m uvicorn deskpilot_backend.main:app --reload
```

Then visit `http://127.0.0.1:8000/api/v1/health`.

## Browser Demo

Open `http://127.0.0.1:8000`, click `Talk (4 seconds)`, and say "open calculator" immediately. The browser calls the existing local microphone command endpoint.

## Native Desktop Shell

```powershell
python -m deskpilot_backend.desktop
```

DeskPilot starts in the Windows system tray. Use the tray menu to choose `Show listening border`, `Hide border`, `Start wake word listening`, `Stop wake word listening`, or `Quit DeskPilot`. Wake-word listening is off by default.

For the native end-to-end demo, choose `Start wake word listening`, say "Hey Jarvis", then speak "open calculator" while the cyan listening border is visible. DeskPilot stops the wake-word microphone stream, records one 4-second local command, transcribes it locally, runs the existing allowlisted assistant action flow, narrates the response with local TTS, hides the border, and resumes wake-word listening if it is still enabled.

The first wake-word start may download/cache openWakeWord's local `hey_jarvis` model. openWakeWord code is Apache-2.0 licensed, while its included pre-trained models are licensed CC BY-NC-SA 4.0.

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

Media controls use fixed Windows virtual media keys and affect the active Windows media session.
Workspace shortcuts use fixed Windows targets only. Folder shortcuts are derived from known local user directories; DeskPilot never accepts spoken paths. System status commands are read-only and use standard-library or Windows `ctypes` calls.
Fixed-site commands use exact allowlisted HTTPS URLs. Search commands encode the query into the trusted search site's `q` parameter and open the results in the default browser; DeskPilot does not make direct HTTP requests.
Notes are saved as plain-text UTF-8 `.txt` files under `~/Documents/DeskPilot/notes`. DeskPilot never accepts spoken note paths or filenames, never overwrites an existing note, and does not sync or send note content anywhere.

## Manual Speech Check

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/speech/speak -ContentType 'application/json' -Body '{"text":"Hello Manuel, DeskPilot is ready."}' | ConvertTo-Json -Depth 5
```

## Manual Assistant Narration Check

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/assistant/commands -ContentType 'application/json' -Body '{"text":"open calculator","speak":true}' | ConvertTo-Json -Depth 5
```

## Manual Transcription Check

The first real transcription may download the local `tiny.en` Whisper model. After that, transcription runs locally on CPU.

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/transcriptions" -F "audio_file=@C:\path\to\recording.wav;type=audio/wav"
```

## Manual Voice Command Check

Record a short English command such as "open calculator" with Windows Voice Recorder. The first real transcription may download the local `tiny.en` Whisper model; after that, transcription runs locally on CPU.

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/voice/commands" -F "audio_file=@C:\path\to\recording.wav;type=audio/wav" -F "speak=true"
```

## Manual Microphone Command Check

This request records locally for 4 seconds, so speak "open calculator" immediately after sending it. The request blocks while recording, then transcribes locally and runs the existing voice-command flow.

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/microphone/commands" -H "Content-Type: application/json" -d "{\"duration_seconds\":4,\"speak\":true}"
```
