# DeskPilot

DeskPilot is a local-first Windows desktop voice assistant portfolio project. This milestone contains a minimal Python backend with a deterministic typed-command router.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

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
