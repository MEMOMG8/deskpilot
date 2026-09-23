# DeskPilot

DeskPilot is a local-first Windows desktop voice assistant portfolio project. This milestone contains a minimal Python backend with a deterministic typed-command router, safe calculator execution, assistant orchestration, and local text-to-speech.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

The install includes `pyttsx3`, which uses the local Windows SAPI voice for text-to-speech.

## Run Tests

```powershell
python -m pytest
```

## Run The API

```powershell
python -m uvicorn deskpilot_backend.main:app --reload
```

Then visit `http://127.0.0.1:8000/api/v1/health`.

## API Endpoints

- `GET /api/v1/health`
- `POST /api/v1/commands`
- `POST /api/v1/actions/execute`
- `POST /api/v1/assistant/commands`
- `POST /api/v1/speech/speak`

## Manual Speech Check

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/speech/speak -ContentType 'application/json' -Body '{"text":"Hello Manuel, DeskPilot is ready."}' | ConvertTo-Json -Depth 5
```
