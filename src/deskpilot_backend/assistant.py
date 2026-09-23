from deskpilot_backend.actions import (
    KeyEventSender,
    ProcessLauncher,
    SystemStatusReader,
    execute_action,
)
from deskpilot_backend.commands import route_command
from deskpilot_backend.models import (
    ActionExecutionRequest,
    AssistantCommandRequest,
    AssistantCommandResponse,
)
from deskpilot_backend.notes import NoteStore
from deskpilot_backend.speech import SpeechEngineError, SpeechEngineFactory, speak_text


def handle_assistant_command(
    command: AssistantCommandRequest,
    launcher: ProcessLauncher | None = None,
    key_event_sender: KeyEventSender | None = None,
    system_status_reader: SystemStatusReader | None = None,
    note_store: NoteStore | None = None,
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

    action_response = execute_action(
        ActionExecutionRequest(
            type=routed_command.action.type,
            target=routed_command.action.target,
            query=routed_command.action.query,
        ),
        launcher=launcher,
        key_event_sender=key_event_sender,
        system_status_reader=system_status_reader,
        note_store=note_store,
    )

    response = AssistantCommandResponse(
        intent=routed_command.intent,
        status="executed",
        requires_confirmation=routed_command.requires_confirmation,
        action=routed_command.action,
        message=action_response.message,
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
