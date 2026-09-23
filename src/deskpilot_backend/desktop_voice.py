from collections.abc import Callable
from dataclasses import dataclass, field

from deskpilot_backend.actions import (
    KeyEventSender,
    ProcessLauncher,
    UnsupportedActionError,
)
from deskpilot_backend.microphone import AudioRecorder, MicrophoneError, record_microphone_wav
from deskpilot_backend.models import VoiceCommandResponse
from deskpilot_backend.speech import SpeechEngineFactory
from deskpilot_backend.transcription import (
    EmptyAudioError,
    TranscriptionServiceError,
    UnsupportedAudioError,
    WhisperTranscriptionService,
)
from deskpilot_backend.voice import handle_voice_command

NATIVE_COMMAND_DURATION_SECONDS = 4
NATIVE_COMMAND_CONTENT_TYPE = "audio/wav"
NATIVE_COMMAND_FILENAME = "native-microphone.wav"


class NativeVoiceCommandError(RuntimeError):
    """Raised when the native wake-word command handoff cannot complete."""


@dataclass
class NativeVoiceCommandService:
    transcription_service: WhisperTranscriptionService = field(
        default_factory=WhisperTranscriptionService
    )
    recorder: AudioRecorder = record_microphone_wav
    launcher: ProcessLauncher | None = None
    key_event_sender: KeyEventSender | None = None
    speech_engine_factory: SpeechEngineFactory | None = None

    def run(self) -> VoiceCommandResponse:
        try:
            audio_bytes = self.recorder(NATIVE_COMMAND_DURATION_SECONDS)
            return handle_voice_command(
                audio_bytes,
                content_type=NATIVE_COMMAND_CONTENT_TYPE,
                filename=NATIVE_COMMAND_FILENAME,
                speak=True,
                transcription_service=self.transcription_service,
                launcher=self.launcher,
                key_event_sender=self.key_event_sender,
                speech_engine_factory=self.speech_engine_factory,
            )
        except (
            MicrophoneError,
            EmptyAudioError,
            UnsupportedAudioError,
            TranscriptionServiceError,
            UnsupportedActionError,
        ) as error:
            raise NativeVoiceCommandError(str(error)) from error


def run_native_voice_handoff(
    *,
    stop_wake_word: Callable[[], None],
    run_voice_command: Callable[[], VoiceCommandResponse],
) -> VoiceCommandResponse:
    stop_wake_word()
    return run_voice_command()
