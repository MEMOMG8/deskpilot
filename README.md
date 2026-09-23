# DeskPilot

DeskPilot is a local-first Windows desktop voice assistant portfolio project. This milestone contains a minimal Python backend with a deterministic typed-command router, safe calculator execution, assistant orchestration, local text-to-speech, offline file transcription, and explicit local microphone commands.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

The install includes `pyttsx3`, which uses the local Windows SAPI voice for text-to-speech, `faster-whisper` and `python-multipart` for offline audio-file transcription, and `sounddevice` for explicit local microphone capture.

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

## API Endpoints

- `GET /api/v1/health`
- `POST /api/v1/commands`
- `POST /api/v1/actions/execute`
- `POST /api/v1/assistant/commands`
- `POST /api/v1/speech/speak`
- `POST /api/v1/transcriptions`
- `POST /api/v1/voice/commands`
- `POST /api/v1/microphone/commands`

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
