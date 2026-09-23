from deskpilot_backend.actions import KeyEventSender, ProcessLauncher, SystemStatusReader
from deskpilot_backend.assistant import handle_assistant_command
from deskpilot_backend.models import (
    AssistantCommandRequest,
    AssistantCommandResponse,
    TranscriptionResponse,
    VoiceCommandResponse,
)
from deskpilot_backend.speech import SpeechEngineFactory
from deskpilot_backend.transcription import WhisperTranscriptionService


def handle_voice_command(
    audio_bytes: bytes,
    *,
    content_type: str | None,
    filename: str | None,
    speak: bool,
    transcription_service: WhisperTranscriptionService,
    launcher: ProcessLauncher | None = None,
    key_event_sender: KeyEventSender | None = None,
    system_status_reader: SystemStatusReader | None = None,
    speech_engine_factory: SpeechEngineFactory | None = None,
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
        speech_engine_factory=speech_engine_factory,
    )

    return VoiceCommandResponse(
        transcription=transcription,
        assistant=assistant_response,
    )
