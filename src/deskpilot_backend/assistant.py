from collections.abc import Mapping

from deskpilot_backend.actions import (
    ActionExecutionError,
    KeyEventSender,
    ProcessLauncher,
    SystemStatusReader,
    execute_action,
)
from deskpilot_backend.command_interpreter import (
    ClarificationStore,
    CommandInterpreter,
    InterpreterProvider,
)
from deskpilot_backend.commands import CommandValidationError, route_command
from deskpilot_backend.intent_routing import HybridCommandInterpreter
from deskpilot_backend.command_interpreter import fixed_command_ids
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
from deskpilot_backend.spotify import SpotifyService
from deskpilot_backend.windows_media import MediaController


def handle_assistant_command(
    command: AssistantCommandRequest,
    launcher: ProcessLauncher | None = None,
    key_event_sender: KeyEventSender | None = None,
    system_status_reader: SystemStatusReader | None = None,
    note_store: NoteStore | None = None,
    reminder_service: ReminderService | None = None,
    settings_store: SettingsStore | None = None,
    spotify_service: SpotifyService | None = None,
    speech_engine_factory: SpeechEngineFactory | None = None,
    custom_aliases: Mapping[str, str] | None = None,
    command_interpreter: CommandInterpreter | None = None,
    command_interpreter_provider: InterpreterProvider | None = None,
    cloud_processing_allowed: bool | None = None,
    clarification_store: ClarificationStore | None = None,
    on_recoverable_error: object | None = None,
    media_controller: MediaController | None = None,
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
            cloud_processing_allowed=(
                _load_settings_for_interpreter(settings_store).cloud_processing_allowed
                if cloud_processing_allowed is None else cloud_processing_allowed is True
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
                spotify_service=spotify_service,
                media_controller=media_controller,
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
        spotify_service=spotify_service,
        media_controller=media_controller,
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
    spotify_service: SpotifyService | None = None,
    media_controller: MediaController | None = None,
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

    try:
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
            spotify_service=spotify_service,
            media_controller=media_controller,
        )
    except ActionExecutionError as error:
        response = AssistantCommandResponse(
            intent=routed_command.intent,
            status="not_supported",
            requires_confirmation=False,
            message=str(error),
        )
        return _maybe_narrate_response(response, speak, speech_engine_factory)

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
    cloud_processing_allowed: bool,
    clarification_store: ClarificationStore | None,
    on_recoverable_error: object | None,
    custom_aliases: Mapping[str, str] | None,
) -> CommandResponse | AssistantCommandResponse | None:
    errors = []
    def notify(message):
        errors.append(message)
        _notify_recoverable(on_recoverable_error, message)
    interpretation = HybridCommandInterpreter(
        provider=command_interpreter_provider, cloud_allowed=cloud_processing_allowed,
        cloud=command_interpreter, on_error=notify,
    ).interpret(command.text)

    if interpretation.unknown:
        if errors:
            return AssistantCommandResponse(
                intent="unknown", status="not_supported", requires_confirmation=False,
                message=errors[-1],
            )
        return None

    if interpretation.clarification_question:
        candidates = interpretation.clarification_candidates
        if (
            clarification_store is None or len(candidates) not in {1, 2}
            or len(set(candidates)) != len(candidates)
            or any(c not in fixed_command_ids() for c in candidates)
            or len(interpretation.clarification_question) > 400
            or interpretation.command_text is not None
        ):
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
