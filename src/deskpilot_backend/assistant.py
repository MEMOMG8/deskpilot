from deskpilot_backend.actions import ProcessLauncher, execute_action
from deskpilot_backend.commands import route_command
from deskpilot_backend.models import (
    ActionExecutionRequest,
    AssistantCommandRequest,
    AssistantCommandResponse,
)
from deskpilot_backend.speech import SpeechEngineError, SpeechEngineFactory, speak_text


def handle_assistant_command(
    command: AssistantCommandRequest,
    launcher: ProcessLauncher | None = None,
    speech_engine_factory: SpeechEngineFactory | None = None,
) -> AssistantCommandResponse:
    routed_command = route_command(command.text)

    if routed_command.action is None:
        response = AssistantCommandResponse(
            intent=routed_command.intent,
            status=routed_command.status,
            requires_confirmation=routed_command.requires_confirmation,
            message=routed_command.message,
        )
        return _maybe_narrate_response(response, command.speak, speech_engine_factory)

    execute_action(
        ActionExecutionRequest(
            type=routed_command.action.type,
            target=routed_command.action.target,
        ),
        launcher=launcher,
    )

    response = AssistantCommandResponse(
        intent=routed_command.intent,
        status="executed",
        requires_confirmation=routed_command.requires_confirmation,
        action=routed_command.action,
        message="Calculator was recognized and launch was requested.",
    )
    return _maybe_narrate_response(response, command.speak, speech_engine_factory)


def _maybe_narrate_response(
    response: AssistantCommandResponse,
    speak: bool,
    speech_engine_factory: SpeechEngineFactory | None,
) -> AssistantCommandResponse:
    if not speak:
        response.speech_result = "not_requested"
        return response

    try:
        speak_text(response.message, engine_factory=speech_engine_factory)
    except SpeechEngineError:
        response.speech_result = "unavailable"
        return response

    response.speech_result = "completed"
    return response
