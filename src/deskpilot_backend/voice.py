from collections.abc import Mapping

from deskpilot_backend.actions import KeyEventSender, ProcessLauncher, SystemStatusReader
from deskpilot_backend.assistant import handle_assistant_command
from deskpilot_backend.models import (
    AssistantCommandRequest,
    AssistantCommandResponse,
    TranscriptionResponse,
    VoiceCommandResponse,
)
from deskpilot_backend.notes import NoteStore
from deskpilot_backend.reminders import ReminderService
from deskpilot_backend.settings import SettingsStore
from deskpilot_backend.speech import SpeechEngineFactory
from deskpilot_backend.transcription import TranscriptionService


def handle_voice_command(
    audio_bytes: bytes,
    *,
    content_type: str | None,
    filename: str | None,
    speak: bool,
    transcription_service: TranscriptionService,
    launcher: ProcessLauncher | None = None,
    key_event_sender: KeyEventSender | None = None,
    system_status_reader: SystemStatusReader | None = None,
    note_store: NoteStore | None = None,
    reminder_service: ReminderService | None = None,
    settings_store: SettingsStore | None = None,
    speech_engine_factory: SpeechEngineFactory | None = None,
    custom_aliases: Mapping[str, str] | None = None,
) -> VoiceCommandResponse:
    transcription = transcription_service.transcribe(
        audio_bytes,
        content_type=content_type,
        filename=filename,
    )

    if not transcription.text.strip():
        return VoiceCommandResponse(
            transcription=transcription,
            assistant=AssistantCommandResponse(
                intent="unknown",
                status="not_supported",
                requires_confirmation=False,
                message="I could not understand a command from that audio.",
            ),
        )

    assistant_response = handle_assistant_command(
        AssistantCommandRequest(text=transcription.text, speak=speak),
        launcher=launcher,
        key_event_sender=key_event_sender,
        system_status_reader=system_status_reader,
        note_store=note_store,
        reminder_service=reminder_service,
        settings_store=settings_store,
        speech_engine_factory=speech_engine_factory,
        custom_aliases=custom_aliases,
    )

    return VoiceCommandResponse(
        transcription=transcription,
        assistant=assistant_response,
    )
