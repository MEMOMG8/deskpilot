# DeskPilot

DeskPilot is a local-first Windows desktop voice assistant portfolio project. This milestone contains only a minimal Python backend foundation.

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
