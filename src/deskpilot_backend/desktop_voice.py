from collections.abc import Callable
from dataclasses import dataclass, field

from deskpilot_backend.actions import (
    KeyEventSender,
    ProcessLauncher,
    SystemStatusReader,
    UnsupportedActionError,
)
from deskpilot_backend.commands import CommandValidationError
from deskpilot_backend.microphone import AudioRecorder, MicrophoneError, record_microphone_wav
from deskpilot_backend.models import VoiceCommandResponse
from deskpilot_backend.notes import NoteStore
from deskpilot_backend.reminders import ReminderService
from deskpilot_backend.speech import SpeechEngineError, SpeechEngineFactory, speak_text
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
NATIVE_REMINDER_HINT = "Say: remind me in one minute to stretch."
NATIVE_UNKNOWN_COMMAND_MESSAGE = "I didn't catch that. Say help for available commands."

CuePlayer = Callable[[], None]
ProgressCallback = Callable[[], None]


class NativeVoiceCommandError(RuntimeError):
    """Raised when the native wake-word command handoff cannot complete."""


def play_recording_start_cue() -> None:
    import winsound

    winsound.MessageBeep(winsound.MB_ICONASTERISK)


@dataclass
class NativeVoiceCommandService:
    transcription_service: WhisperTranscriptionService = field(
        default_factory=WhisperTranscriptionService
    )
    recorder: AudioRecorder = record_microphone_wav
    launcher: ProcessLauncher | None = None
    key_event_sender: KeyEventSender | None = None
    system_status_reader: SystemStatusReader | None = None
    note_store: NoteStore | None = None
    reminder_service: ReminderService | None = None
    speech_engine_factory: SpeechEngineFactory | None = None
    cue_player: CuePlayer = play_recording_start_cue
    on_processing_started: ProgressCallback | None = None

    def run(self) -> VoiceCommandResponse:
        try:
            try:
                self.cue_player()
            except Exception as error:
                raise NativeVoiceCommandError("Recording cue is unavailable.") from error

            audio_bytes = self.recorder(NATIVE_COMMAND_DURATION_SECONDS)
            if self.on_processing_started is not None:
                self.on_processing_started()

            response = handle_voice_command(
                audio_bytes,
                content_type=NATIVE_COMMAND_CONTENT_TYPE,
                filename=NATIVE_COMMAND_FILENAME,
                speak=False,
                transcription_service=self.transcription_service,
                launcher=self.launcher,
                key_event_sender=self.key_event_sender,
                system_status_reader=self.system_status_reader,
                note_store=self.note_store,
                reminder_service=self.reminder_service,
            )
            _narrate_native_response(response, self.speech_engine_factory)
            return response
        except CommandValidationError as error:
            message = _native_validation_message(error)
            _try_speak_native_validation_message(message, self.speech_engine_factory)
            raise NativeVoiceCommandError(message) from error
        except (
            MicrophoneError,
            EmptyAudioError,
            UnsupportedAudioError,
            TranscriptionServiceError,
            UnsupportedActionError,
        ) as error:
            raise NativeVoiceCommandError(str(error)) from error


def _narrate_native_response(
    response: VoiceCommandResponse,
    speech_engine_factory: SpeechEngineFactory | None,
) -> None:
    if response.assistant.status == "not_supported":
        response.assistant.message = NATIVE_UNKNOWN_COMMAND_MESSAGE

    try:
        speak_text(response.assistant.message, engine_factory=speech_engine_factory)
    except SpeechEngineError:
        response.assistant.speech_result = "unavailable"
        return

    response.assistant.speech_result = "completed"


def _native_validation_message(error: CommandValidationError) -> str:
    message = str(error)
    if "reminder" in message.casefold() or "remind me" in message.casefold():
        return NATIVE_REMINDER_HINT

    return message


def _try_speak_native_validation_message(
    message: str,
    speech_engine_factory: SpeechEngineFactory | None,
) -> None:
    try:
        speak_text(message, engine_factory=speech_engine_factory)
    except SpeechEngineError:
        return


def run_native_voice_handoff(
    *,
    stop_wake_word: Callable[[], None],
    run_voice_command: Callable[[], VoiceCommandResponse],
) -> VoiceCommandResponse:
    stop_wake_word()
    return run_voice_command()
