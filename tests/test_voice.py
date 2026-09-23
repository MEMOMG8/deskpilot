import io
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from deskpilot_backend.main import (
    app,
    get_process_launcher,
    get_speech_engine_factory,
    get_transcription_service,
)
from deskpilot_backend.models import TranscriptionResponse
from deskpilot_backend.transcription import (
    TranscriptionServiceError,
    UnsupportedAudioError,
)


class FakeTranscriptionService:
    def __init__(self, text: str = "open calculator") -> None:
        self.text = text
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
            text=self.text,
            language="en",
        )


class FailingTranscriptionService(FakeTranscriptionService):
    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str | None,
        filename: str | None = None,
    ) -> TranscriptionResponse:
        raise TranscriptionServiceError("Local transcription is unavailable.")


class UnsupportedUploadTranscriptionService(FakeTranscriptionService):
    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str | None,
        filename: str | None = None,
    ) -> TranscriptionResponse:
        raise UnsupportedAudioError("Unsupported audio upload type.")


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


@contextmanager
def mocked_voice_dependencies(
    transcription_service: object,
    launcher: RecordingLauncher,
    speech_engine_factory: object | None = None,
) -> Iterator[None]:
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


def test_voice_command_transcribes_open_calculator_and_executes_safely() -> None:
    transcription_service = FakeTranscriptionService("open calculator")
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_voice_dependencies(transcription_service, launcher):
        response = client.post(
            "/api/v1/voice/commands",
            files={"audio_file": ("command.wav", io.BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "transcription": {
            "status": "completed",
            "message": "Transcription completed.",
            "text": "open calculator",
            "language": "en",
        },
        "assistant": {
            "intent": "open_app",
            "status": "executed",
            "requires_confirmation": False,
            "message": "Calculator was recognized and launch was requested.",
            "speech_result": "not_requested",
            "action": {"type": "open_app", "target": "calculator"},
        },
    }
    assert launcher.commands == [["calc.exe"]]


def test_voice_command_forwards_speak_true_to_assistant_narration() -> None:
    transcription_service = FakeTranscriptionService("open calculator")
    launcher = RecordingLauncher()
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_voice_dependencies(
        transcription_service,
        launcher,
        speech_engine_factory=lambda: engine,
    ):
        response = client.post(
            "/api/v1/voice/commands",
            files={"audio_file": ("command.wav", io.BytesIO(b"audio"), "audio/wav")},
            data={"speak": "true"},
        )

    assert response.status_code == 200
    assert response.json()["assistant"]["speech_result"] == "completed"
    assert launcher.commands == [["calc.exe"]]
    assert engine.spoken_text == ["Calculator was recognized and launch was requested."]
    assert engine.completed is True


def test_voice_command_blank_transcription_executes_nothing() -> None:
    transcription_service = FakeTranscriptionService("   ")
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_voice_dependencies(transcription_service, launcher):
        response = client.post(
            "/api/v1/voice/commands",
            files={"audio_file": ("blank.wav", io.BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "transcription": {
            "status": "completed",
            "message": "Transcription completed.",
            "text": "   ",
            "language": "en",
        },
        "assistant": {
            "intent": "unknown",
            "status": "not_supported",
            "requires_confirmation": False,
            "message": "I could not understand a command from that audio.",
            "speech_result": "not_requested",
        },
    }
    assert launcher.commands == []


def test_voice_command_transcription_failure_executes_nothing() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_voice_dependencies(FailingTranscriptionService(), launcher):
        response = client.post(
            "/api/v1/voice/commands",
            files={"audio_file": ("command.wav", io.BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Local transcription is unavailable."}
    assert launcher.commands == []


def test_voice_command_unsupported_upload_is_rejected_before_action() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_voice_dependencies(UnsupportedUploadTranscriptionService(), launcher):
        response = client.post(
            "/api/v1/voice/commands",
            files={"audio_file": ("notes.txt", io.BytesIO(b"text"), "text/plain")},
        )

    assert response.status_code == 415
    assert response.json() == {"detail": "Unsupported audio upload type."}
    assert launcher.commands == []
