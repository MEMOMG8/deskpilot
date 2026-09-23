from fastapi import FastAPI

app = FastAPI(title="DeskPilot")


@app.get("/api/v1/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "deskpilot"}
