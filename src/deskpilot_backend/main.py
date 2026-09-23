from fastapi import FastAPI

from deskpilot_backend.commands import route_command
from deskpilot_backend.models import CommandRequest, CommandResponse

app = FastAPI(title="DeskPilot")


@app.get("/api/v1/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "deskpilot"}


@app.post(
    "/api/v1/commands",
    response_model=CommandResponse,
    response_model_exclude_none=True,
)
def create_command(command: CommandRequest) -> CommandResponse:
    return route_command(command.text)
