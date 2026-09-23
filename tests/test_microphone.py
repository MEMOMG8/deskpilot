from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from deskpilot_backend.main import (
    app,
    get_audio_recorder,
    get_process_launcher,
    get_speech_engine_factory,
    get_transcription_service,
)
from deskpilot_backend.microphone import MicrophoneError, encode_wav
from deskpilot_backend.models import TranscriptionResponse


class FakeTranscriptionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

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
            text="open calculator",
            language="en",
        )


class RecordingLauncher:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> object:
        self.commands.append(command)
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


@contextmanager
def mocked_microphone_dependencies(
    recorder: object,
    transcription_service: FakeTranscriptionService,
    launcher: RecordingLauncher,
    speech_engine_factory: object | None = None,
) -> Iterator[None]:
    app.dependency_overrides[get_audio_recorder] = lambda: recorder
    app.dependency_overrides[get_transcription_service] = lambda: transcription_service
    app.dependency_overrides[get_process_launcher] = lambda: launcher

    if speech_engine_factory is not None:
        app.dependency_overrides[get_speech_engine_factory] = (
            lambda: speech_engine_factory
        )

    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_microphone_command_records_four_seconds_and_uses_voice_flow() -> None:
    wav_audio = encode_wav(b"\x00\x00" * 16000)
    recorder = FakeRecorder(wav_audio)
    transcription_service = FakeTranscriptionService()
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_microphone_dependencies(recorder, transcription_service, launcher):
        response = client.post(
            "/api/v1/microphone/commands",
            json={"duration_seconds": 4},
        )

    assert response.status_code == 200
    assert response.json()["assistant"]["status"] == "executed"
    assert recorder.durations == [4]
    assert transcription_service.calls == [
        {
            "audio_bytes": wav_audio,
            "content_type": "audio/wav",
            "filename": "microphone.wav",
        }
    ]
    assert launcher.commands == [["calc.exe"]]


def test_microphone_command_forwards_speak_true() -> None:
    recorder = FakeRecorder(encode_wav(b"\x00\x00" * 16000))
    transcription_service = FakeTranscriptionService()
    launcher = RecordingLauncher()
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_microphone_dependencies(
        recorder,
        transcription_service,
        launcher,
        speech_engine_factory=lambda: engine,
    ):
        response = client.post(
            "/api/v1/microphone/commands",
            json={"duration_seconds": 4, "speak": True},
        )

    assert response.status_code == 200
    assert response.json()["assistant"]["speech_result"] == "completed"
    assert engine.spoken_text == ["Opening Calculator."]
    assert launcher.commands == [["calc.exe"]]


def test_microphone_command_rejects_invalid_durations() -> None:
    client = TestClient(app)

    too_short = client.post(
        "/api/v1/microphone/commands",
        json={"duration_seconds": 0},
    )
    too_long = client.post(
        "/api/v1/microphone/commands",
        json={"duration_seconds": 11},
    )

    assert too_short.status_code == 422
    assert too_long.status_code == 422


def test_microphone_failure_stops_before_transcription_action_and_speech() -> None:
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

    def speech_must_not_run() -> FakeSpeechEngine:
        raise AssertionError("speech should not run")

    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_microphone_dependencies(
        FailingRecorder(),
        MustNotTranscribe(),
        launcher,
        speech_engine_factory=speech_must_not_run,
    ):
        response = client.post(
            "/api/v1/microphone/commands",
            json={"duration_seconds": 4, "speak": True},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Local microphone recording is unavailable."}
    assert launcher.commands == []
