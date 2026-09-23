from typing import Literal

from pydantic import BaseModel, field_validator


class CommandRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value


class CommandAction(BaseModel):
    type: Literal["open_app"]
    target: Literal["calculator"]


class CommandResponse(BaseModel):
    intent: Literal["open_app", "help", "unknown"]
    status: Literal["planned", "completed", "not_supported"]
    requires_confirmation: bool
    message: str
    action: CommandAction | None = None


class ActionExecutionRequest(BaseModel):
    type: str
    target: str


class ActionExecutionResponse(BaseModel):
    status: Literal["executed"]
    executed: bool
    action: ActionExecutionRequest
    message: str


class AssistantCommandResponse(BaseModel):
    intent: Literal["open_app", "help", "unknown"]
    status: Literal["executed", "completed", "not_supported"]
    requires_confirmation: bool
    message: str
    action: CommandAction | None = None
