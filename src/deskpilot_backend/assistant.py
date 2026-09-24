import os
from collections.abc import Mapping

from deskpilot_backend.actions import (
    KeyEventSender,
    ProcessLauncher,
    SystemStatusReader,
    execute_action,
)
from deskpilot_backend.command_interpreter import (
    ClarificationStore,
    CommandInterpreter,
    CommandInterpreterError,
    InterpreterProvider,
)
from deskpilot_backend.commands import CommandValidationError, route_command
from deskpilot_backend.models import (
    ActionExecutionRequest,
    AssistantCommandRequest,
    AssistantCommandResponse,
    CommandResponse,
)
from deskpilot_backend.notes import NoteStore
from deskpilot_backend.reminders import ReminderService
from deskpilot_backend.settings import DeskPilotSettings, SettingsStore
from deskpilot_backend.speech import SpeechEngineError, SpeechEngineFactory, speak_text


def handle_assistant_command(
    command: AssistantCommandRequest,
    launcher: ProcessLauncher | None = None,
    key_event_sender: KeyEventSender | None = None,
    system_status_reader: SystemStatusReader | None = None,
    note_store: NoteStore | None = None,
    reminder_service: ReminderService | None = None,
    settings_store: SettingsStore | None = None,
    speech_engine_factory: SpeechEngineFactory | None = None,
    custom_aliases: Mapping[str, str] | None = None,
    command_interpreter: CommandInterpreter | None = None,
    command_interpreter_provider: InterpreterProvider | None = None,
    clarification_store: ClarificationStore | None = None,
    on_recoverable_error: object | None = None,
) -> AssistantCommandResponse:
    resolved_command = _resolve_pending_clarification(
        command.text,
        clarification_store,
    )
    if resolved_command == "cancel":
        response = AssistantCommandResponse(
            intent="cancel",
            status="completed",
            requires_confirmation=False,
            message="Cancelled.",
        )
        return _maybe_narrate_response(response, command.speak, speech_engine_factory)

    command_text = resolved_command or command.text
    routed_command = route_command(command_text, custom_aliases=custom_aliases)

    if resolved_command is None and _is_unknown(routed_command):
        interpreted_result = _try_interpret_unknown_command(
            command,
            command_interpreter=command_interpreter,
            command_interpreter_provider=_resolve_interpreter_provider(
                settings_store,
                command_interpreter_provider,
            ),
            clarification_store=clarification_store,
            on_recoverable_error=on_recoverable_error,
            custom_aliases=custom_aliases,
        )
        if isinstance(interpreted_result, CommandResponse):
            return _execute_routed_command(
                interpreted_result,
                speak=command.speak,
                launcher=launcher,
                key_event_sender=key_event_sender,
                system_status_reader=system_status_reader,
                note_store=note_store,
                reminder_service=reminder_service,
                settings_store=settings_store,
                speech_engine_factory=speech_engine_factory,
            )

        if interpreted_result is not None:
            return _maybe_narrate_response(
                interpreted_result,
                command.speak,
                speech_engine_factory,
            )

    if not _is_unknown(routed_command) and clarification_store is not None:
        clarification_store.clear()

    return _execute_routed_command(
        routed_command,
        speak=command.speak,
        launcher=launcher,
        key_event_sender=key_event_sender,
        system_status_reader=system_status_reader,
        note_store=note_store,
        reminder_service=reminder_service,
        settings_store=settings_store,
        speech_engine_factory=speech_engine_factory,
    )


def _execute_routed_command(
    routed_command: CommandResponse,
    *,
    speak: bool,
    launcher: ProcessLauncher | None = None,
    key_event_sender: KeyEventSender | None = None,
    system_status_reader: SystemStatusReader | None = None,
    note_store: NoteStore | None = None,
    reminder_service: ReminderService | None = None,
    settings_store: SettingsStore | None = None,
    speech_engine_factory: SpeechEngineFactory | None = None,
) -> AssistantCommandResponse:
    if routed_command.action is None:
        response = AssistantCommandResponse(
            intent=routed_command.intent,
            status=routed_command.status,
            requires_confirmation=routed_command.requires_confirmation,
            message=routed_command.message,
        )
        return _maybe_narrate_response(response, speak, speech_engine_factory)

    action_response = execute_action(
        ActionExecutionRequest(
            type=routed_command.action.type,
            target=routed_command.action.target,
            query=routed_command.action.query,
            minutes=routed_command.action.minutes,
        ),
        launcher=launcher,
        key_event_sender=key_event_sender,
        system_status_reader=system_status_reader,
        note_store=note_store,
        reminder_service=reminder_service,
        settings_store=settings_store,
    )

    response = AssistantCommandResponse(
        intent=routed_command.intent,
        status="executed",
        requires_confirmation=routed_command.requires_confirmation,
        action=routed_command.action,
        message=action_response.message,
    )
    return _maybe_narrate_response(response, speak, speech_engine_factory)


def _try_interpret_unknown_command(
    command: AssistantCommandRequest,
    *,
    command_interpreter: CommandInterpreter | None,
    command_interpreter_provider: InterpreterProvider,
    clarification_store: ClarificationStore | None,
    on_recoverable_error: object | None,
    custom_aliases: Mapping[str, str] | None,
) -> CommandResponse | AssistantCommandResponse | None:
    if command_interpreter_provider == "local" or command_interpreter is None:
        return None

    if not _openai_api_key_available():
        if command_interpreter_provider == "openai":
            _notify_recoverable(
                on_recoverable_error,
                "Natural-language command understanding needs OPENAI_API_KEY.",
            )
            return AssistantCommandResponse(
                intent="unknown",
                status="not_supported",
                requires_confirmation=False,
                message="Natural-language command understanding needs OPENAI_API_KEY.",
            )
        return None

    try:
        interpretation = command_interpreter.interpret(command.text)
    except CommandInterpreterError:
        _notify_recoverable(
            on_recoverable_error,
            "Natural-language command understanding is unavailable.",
        )
        return None

    if interpretation.unknown:
        return None

    if interpretation.clarification_question:
        if clarification_store is None or not interpretation.clarification_candidates:
            return None
        clarification_store.set(interpretation.clarification_candidates)
        return AssistantCommandResponse(
            intent="unknown",
            status="not_supported",
            requires_confirmation=True,
            message=interpretation.clarification_question,
        )

    if interpretation.command_text is None:
        return None

    try:
        routed_command = route_command(
            interpretation.command_text,
            custom_aliases=custom_aliases,
        )
    except CommandValidationError:
        return None

    if _is_unknown(routed_command):
        return None

    return routed_command


def _resolve_interpreter_provider(
    settings_store: SettingsStore | None,
    command_interpreter_provider: InterpreterProvider | None,
) -> InterpreterProvider:
    if command_interpreter_provider is not None:
        return command_interpreter_provider

    settings = _load_settings_for_interpreter(settings_store)
    return settings.voice_command_interpreter_provider


def _load_settings_for_interpreter(
    settings_store: SettingsStore | None,
) -> DeskPilotSettings:
    if settings_store is None:
        return DeskPilotSettings()

    try:
        return settings_store.load_or_create()
    except Exception:
        return DeskPilotSettings()


def _resolve_pending_clarification(
    text: str,
    clarification_store: ClarificationStore | None,
) -> str | None:
    if clarification_store is None:
        return None
    return clarification_store.resolve(text)


def _is_unknown(routed_command: CommandResponse) -> bool:
    return routed_command.intent == "unknown" and routed_command.status == "not_supported"


def _openai_api_key_available() -> bool:
    api_key = os.getenv("OPENAI_API_KEY")
    return isinstance(api_key, str) and bool(api_key.strip())


def _notify_recoverable(callback: object | None, message: str) -> None:
    if callable(callback):
        callback(message)


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
