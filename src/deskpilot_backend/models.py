from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CommandRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value


class CommandAction(BaseModel):
    type: Literal[
        "open_app",
        "media_key",
        "workspace_shortcut",
        "system_status",
        "open_url",
        "web_search",
        "note",
    ]
    target: Literal[
        "calculator",
        "notepad",
        "file_explorer",
        "settings",
        "browser",
        "volume_up",
        "volume_down",
        "mute",
        "play_pause",
        "next_track",
        "previous_track",
        "downloads",
        "documents",
        "desktop",
        "task_manager",
        "battery",
        "memory",
        "disk",
        "google",
        "youtube",
        "github",
        "web",
        "create",
        "read_latest",
        "count",
        "open_folder",
    ]
    query: str | None = None


class CommandResponse(BaseModel):
    intent: Literal[
        "open_app",
        "media_control",
        "workspace_shortcut",
        "system_status",
        "open_site",
        "web_search",
        "notes",
        "get_time",
        "get_date",
        "help",
        "unknown",
    ]
    status: Literal["planned", "completed", "not_supported"]
    requires_confirmation: bool
    message: str
    action: CommandAction | None = None


class ActionExecutionRequest(BaseModel):
    type: str
    target: str
    query: str | None = None


class ActionExecutionResponse(BaseModel):
    status: Literal["executed"]
    executed: bool
    action: ActionExecutionRequest
    message: str


class AssistantCommandResponse(BaseModel):
    intent: Literal[
        "open_app",
        "media_control",
        "workspace_shortcut",
        "system_status",
        "open_site",
        "web_search",
        "notes",
        "get_time",
        "get_date",
        "help",
        "unknown",
    ]
    status: Literal["executed", "completed", "not_supported"]
    requires_confirmation: bool
    message: str
    speech_result: Literal["not_requested", "completed", "unavailable"] = (
        "not_requested"
    )
    action: CommandAction | None = None


class AssistantCommandRequest(CommandRequest):
    speak: bool = False


class SpeechRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value


class SpeechResponse(BaseModel):
    status: Literal["completed"]
    message: str


class TranscriptionResponse(BaseModel):
    status: Literal["completed"]
    message: str
    text: str
    language: str | None = None


class VoiceCommandResponse(BaseModel):
    transcription: TranscriptionResponse
    assistant: AssistantCommandResponse


class MicrophoneCommandRequest(BaseModel):
    duration_seconds: int = Field(ge=1, le=10)
    speak: bool = False
