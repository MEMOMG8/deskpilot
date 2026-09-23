import pytest

from deskpilot_backend.actions import KEYEVENTF_KEYUP, VK_MEDIA_PLAY_PAUSE
from deskpilot_backend.desktop_state import NativeWakeWordCommandController
from deskpilot_backend.desktop_voice import (
    NATIVE_COMMAND_DURATION_SECONDS,
    NATIVE_REMINDER_HINT,
    NativeVoiceCommandError,
    NativeVoiceCommandService,
    run_native_voice_handoff,
)
from deskpilot_backend.microphone import MicrophoneError, encode_wav
from deskpilot_backend.models import TranscriptionResponse, VoiceCommandResponse


class FakeTranscriptionService:
    def __init__(self, text: str = "open calculator") -> None:
        self.calls: list[dict[str, object]] = []
        self.text = text

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str | None,
        filename: str | None = None,
    ) -> TranscriptionResponse:
        self.calls.append(
            {
                "audio_bytes": audio_bytes,
                "content_type": content_type,
                "filename": filename,
            }
        )
        return TranscriptionResponse(
            status="completed",
            message="Transcription completed.",
            text=self.text,
            language="en",
        )


class RecordingLauncher:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> object:
        self.commands.append(command)
        return object()


class RecordingKeyEventSender:
    def __init__(self) -> None:
        self.events: list[tuple[int, int]] = []

    def __call__(self, virtual_key: int, flags: int) -> object:
        self.events.append((virtual_key, flags))
        return object()


class FakeSpeechEngine:
    def __init__(self) -> None:
        self.spoken_text: list[str] = []
        self.completed = False

    def say(self, text: str) -> None:
        self.spoken_text.append(text)

    def runAndWait(self) -> None:
        self.completed = True


class FakeRecorder:
    def __init__(self, audio_bytes: bytes) -> None:
        self.audio_bytes = audio_bytes
        self.durations: list[int] = []

    def __call__(self, duration_seconds: int) -> bytes:
        self.durations.append(duration_seconds)
        return self.audio_bytes


def test_native_voice_command_uses_existing_voice_pipeline_with_speech() -> None:
    wav_audio = encode_wav(b"\x00\x00" * 16000)
    recorder = FakeRecorder(wav_audio)
    transcription_service = FakeTranscriptionService()
    launcher = RecordingLauncher()
    engine = FakeSpeechEngine()
    service = NativeVoiceCommandService(
        transcription_service=transcription_service,
        recorder=recorder,
        launcher=launcher,
        speech_engine_factory=lambda: engine,
    )

    response = service.run()

    assert isinstance(response, VoiceCommandResponse)
    assert response.assistant.status == "executed"
    assert response.assistant.speech_result == "completed"
    assert recorder.durations == [NATIVE_COMMAND_DURATION_SECONDS]
    assert transcription_service.calls == [
        {
            "audio_bytes": wav_audio,
            "content_type": "audio/wav",
            "filename": "native-microphone.wav",
        }
    ]
    assert launcher.commands == [["calc.exe"]]
    assert engine.spoken_text == ["Opening Calculator."]
    assert engine.completed is True


def test_native_voice_command_can_execute_mocked_media_key_command() -> None:
    wav_audio = encode_wav(b"\x00\x00" * 16000)
    recorder = FakeRecorder(wav_audio)
    launcher = RecordingLauncher()
    key_event_sender = RecordingKeyEventSender()
    engine = FakeSpeechEngine()
    service = NativeVoiceCommandService(
        transcription_service=FakeTranscriptionService("pause music"),
        recorder=recorder,
        launcher=launcher,
        key_event_sender=key_event_sender,
        speech_engine_factory=lambda: engine,
    )

    response = service.run()

    assert response.assistant.intent == "media_control"
    assert response.assistant.status == "executed"
    assert response.assistant.message == "Toggling media playback."
    assert response.assistant.speech_result == "completed"
    assert launcher.commands == []
    assert key_event_sender.events == [
        (VK_MEDIA_PLAY_PAUSE, 0),
        (VK_MEDIA_PLAY_PAUSE, KEYEVENTF_KEYUP),
    ]
    assert engine.spoken_text == ["Toggling media playback."]


def test_native_voice_reminder_validation_error_is_narrated_helpfully() -> None:
    wav_audio = encode_wav(b"\x00\x00" * 16000)
    recorder = FakeRecorder(wav_audio)
    launcher = RecordingLauncher()
    engine = FakeSpeechEngine()
    service = NativeVoiceCommandService(
        transcription_service=FakeTranscriptionService(
            "remind me in banana minutes to stretch"
        ),
        recorder=recorder,
        launcher=launcher,
        speech_engine_factory=lambda: engine,
    )

    with pytest.raises(NativeVoiceCommandError) as error:
        service.run()

    assert str(error.value) == NATIVE_REMINDER_HINT
    assert launcher.commands == []
    assert engine.spoken_text == [NATIVE_REMINDER_HINT]
    assert engine.completed is True


def test_native_voice_command_failure_is_controlled() -> None:
    class FailingRecorder:
        def __call__(self, duration_seconds: int) -> bytes:
            raise MicrophoneError("Local microphone recording is unavailable.")

    class MustNotTranscribe(FakeTranscriptionService):
        def transcribe(
            self,
            audio_bytes: bytes,
            *,
            content_type: str | None,
            filename: str | None = None,
        ) -> TranscriptionResponse:
            raise AssertionError("transcription should not run")

    service = NativeVoiceCommandService(
        transcription_service=MustNotTranscribe(),
        recorder=FailingRecorder(),
        launcher=RecordingLauncher(),
        speech_engine_factory=lambda: FakeSpeechEngine(),
    )

    with pytest.raises(NativeVoiceCommandError) as error:
        service.run()

    assert str(error.value) == "Local microphone recording is unavailable."


def test_native_voice_command_failure_recovery_can_resume_wake_word() -> None:
    class FailingRecorder:
        def __call__(self, duration_seconds: int) -> bytes:
            raise MicrophoneError("Local microphone recording is unavailable.")

    controller = NativeWakeWordCommandController()
    service = NativeVoiceCommandService(
        transcription_service=FakeTranscriptionService(),
        recorder=FailingRecorder(),
    )

    controller.enable_wake_word()
    assert controller.begin_command_after_wake_word() is True

    with pytest.raises(NativeVoiceCommandError):
        service.run()

    assert controller.finish_command() is True
    assert controller.command_in_progress is False


def test_native_voice_handoff_stops_wake_word_before_recording() -> None:
    events: list[str] = []

    def stop_wake_word() -> None:
        events.append("wake_stopped")

    def run_voice_command() -> VoiceCommandResponse:
        assert events == ["wake_stopped"]
        events.append("command_recorded")
        return NativeVoiceCommandService(
            transcription_service=FakeTranscriptionService("help"),
            recorder=FakeRecorder(encode_wav(b"\x00\x00" * 16000)),
            launcher=RecordingLauncher(),
            speech_engine_factory=lambda: FakeSpeechEngine(),
        ).run()

    response = run_native_voice_handoff(
        stop_wake_word=stop_wake_word,
        run_voice_command=run_voice_command,
    )

    assert response.assistant.intent == "help"
    assert events == ["wake_stopped", "command_recorded"]
