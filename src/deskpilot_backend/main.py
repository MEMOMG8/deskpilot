from fastapi import Depends, FastAPI, HTTPException

from deskpilot_backend.actions import ProcessLauncher, UnsupportedActionError, execute_action
from deskpilot_backend.assistant import handle_assistant_command
from deskpilot_backend.commands import route_command
from deskpilot_backend.models import (
    ActionExecutionRequest,
    ActionExecutionResponse,
    AssistantCommandResponse,
    CommandRequest,
    CommandResponse,
)

app = FastAPI(title="DeskPilot")


def get_process_launcher() -> ProcessLauncher | None:
    return None


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


@app.post("/api/v1/actions/execute", response_model=ActionExecutionResponse)
def execute_planned_action(
    action: ActionExecutionRequest,
) -> ActionExecutionResponse:
    try:
        return execute_action(action)
    except UnsupportedActionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post(
    "/api/v1/assistant/commands",
    response_model=AssistantCommandResponse,
    response_model_exclude_none=True,
)
def create_assistant_command(
    command: CommandRequest,
    process_launcher: ProcessLauncher | None = Depends(get_process_launcher),
) -> AssistantCommandResponse:
    try:
        return handle_assistant_command(command, launcher=process_launcher)
    except UnsupportedActionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
