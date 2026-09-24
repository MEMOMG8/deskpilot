import io
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi.testclient import TestClient

from deskpilot_backend.main import app, get_transcription_service
from deskpilot_backend.models import TranscriptionResponse
from deskpilot_backend.transcription import (
    EmptyAudioError,
    OpenAITranscriptionService,
    ProviderTranscriptionService,
    TranscriptionServiceError,
    UnsupportedAudioError,
    validate_audio_upload,
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
        self.calls.append(
            {
                "audio_bytes": audio_bytes,
                "content_type": content_type,
                "filename": filename,
            }
        )
        raise TranscriptionServiceError("Transcription unavailable.")


@dataclass
class FakeTranscript:
    text: str
    language: str | None = "en"


class FakeOpenAITranscriptions:
    def __init__(self, transcript: object, *, fail: bool = False) -> None:
        self.transcript = transcript
        self.fail = fail
        self.calls: list[dict[str, object]] = []
        self.file_path: str | None = None

    def create(self, **kwargs: object) -> object:
        audio_file = kwargs["file"]
        self.file_path = audio_file.name
        assert os.path.exists(self.file_path)
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("network unavailable")
        return self.transcript


class FakeOpenAIAudio:
    def __init__(self, transcriptions: FakeOpenAITranscriptions) -> None:
        self.transcriptions = transcriptions


class FakeOpenAIClient:
    def __init__(self, transcriptions: FakeOpenAITranscriptions) -> None:
        self.audio = FakeOpenAIAudio(transcriptions)


@contextmanager
def mocked_transcription_service(service: object) -> Iterator[None]:
    app.dependency_overrides[get_transcription_service] = lambda: service
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_transcription_endpoint_returns_mocked_transcription() -> None:
    service = FakeTranscriptionService()
    client = TestClient(app)

    with mocked_transcription_service(service):
        response = client.post(
            "/api/v1/transcriptions",
            files={"audio_file": ("command.wav", io.BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "message": "Transcription completed.",
        "text": "open calculator",
        "language": "en",
    }
    assert service.calls == [
        {
            "audio_bytes": b"audio",
            "content_type": "audio/wav",
            "filename": "command.wav",
        }
    ]


def test_transcription_endpoint_requires_file() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/transcriptions")

    assert response.status_code == 422


def test_audio_upload_validation_rejects_empty_file() -> None:
    try:
        validate_audio_upload("audio/wav", b"")
    except EmptyAudioError as error:
        assert str(error) == "Uploaded audio file is empty."
    else:
        raise AssertionError("Expected EmptyAudioError")


def test_transcription_endpoint_rejects_empty_file() -> None:
    class EmptyRejectingService(FakeTranscriptionService):
        def transcribe(
            self,
            audio_bytes: bytes,
            *,
            content_type: str | None,
            filename: str | None = None,
        ) -> TranscriptionResponse:
            raise EmptyAudioError("Uploaded audio file is empty.")

    client = TestClient(app)

    with mocked_transcription_service(EmptyRejectingService()):
        response = client.post(
            "/api/v1/transcriptions",
            files={"audio_file": ("empty.wav", io.BytesIO(b""), "audio/wav")},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Uploaded audio file is empty."}


def test_audio_upload_validation_rejects_unsupported_upload() -> None:
    try:
        validate_audio_upload("text/plain", b"not audio")
    except UnsupportedAudioError as error:
        assert str(error) == "Unsupported audio upload type."
    else:
        raise AssertionError("Expected UnsupportedAudioError")


def test_transcription_endpoint_rejects_unsupported_upload() -> None:
    class UnsupportedRejectingService(FakeTranscriptionService):
        def transcribe(
            self,
            audio_bytes: bytes,
            *,
            content_type: str | None,
            filename: str | None = None,
        ) -> TranscriptionResponse:
            raise UnsupportedAudioError("Unsupported audio upload type.")

    client = TestClient(app)

    with mocked_transcription_service(UnsupportedRejectingService()):
        response = client.post(
            "/api/v1/transcriptions",
            files={"audio_file": ("notes.txt", io.BytesIO(b"text"), "text/plain")},
        )

    assert response.status_code == 415
    assert response.json() == {"detail": "Unsupported audio upload type."}


def test_transcription_endpoint_returns_controlled_service_failure() -> None:
    class FailingService(FakeTranscriptionService):
        def transcribe(
            self,
            audio_bytes: bytes,
            *,
            content_type: str | None,
            filename: str | None = None,
        ) -> TranscriptionResponse:
            raise TranscriptionServiceError("Local transcription is unavailable.")

    client = TestClient(app)

    with mocked_transcription_service(FailingService()):
        response = client.post(
            "/api/v1/transcriptions",
            files={"audio_file": ("command.wav", io.BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Local transcription is unavailable."}


def test_provider_auto_uses_openai_when_api_key_exists() -> None:
    local = FakeTranscriptionService("local text")
    cloud = FakeTranscriptionService("cloud text")
    service = ProviderTranscriptionService(
        provider="auto",
        local_service=local,
        openai_service=cloud,
        api_key_getter=lambda name: "test-key",
    )

    response = service.transcribe(
        b"audio",
        content_type="audio/wav",
        filename="command.wav",
    )

    assert response.text == "cloud text"
    assert cloud.calls
    assert local.calls == []


def test_provider_auto_uses_local_when_api_key_is_missing() -> None:
    local = FakeTranscriptionService("local text")
    cloud = FakeTranscriptionService("cloud text")
    service = ProviderTranscriptionService(
        provider="auto",
        local_service=local,
        openai_service=cloud,
        api_key_getter=lambda name: None,
    )

    response = service.transcribe(
        b"audio",
        content_type="audio/wav",
        filename="command.wav",
    )

    assert response.text == "local text"
    assert local.calls
    assert cloud.calls == []


def test_provider_openai_missing_api_key_falls_back_to_local() -> None:
    fallback_messages: list[str] = []
    local = FakeTranscriptionService("local text")
    cloud = FakeTranscriptionService("cloud text")
    service = ProviderTranscriptionService(
        provider="openai",
        local_service=local,
        openai_service=cloud,
        api_key_getter=lambda name: " ",
        on_fallback=fallback_messages.append,
    )

    response = service.transcribe(
        b"audio",
        content_type="audio/wav",
        filename="command.wav",
    )

    assert response.text == "local text"
    assert local.calls
    assert cloud.calls == []
    assert fallback_messages == [
        "OpenAI transcription is not configured; using local transcription."
    ]


def test_provider_cloud_failure_falls_back_to_local() -> None:
    fallback_messages: list[str] = []
    local = FakeTranscriptionService("local text")
    cloud = FailingTranscriptionService("cloud text")
    service = ProviderTranscriptionService(
        provider="auto",
        local_service=local,
        openai_service=cloud,
        api_key_getter=lambda name: "test-key",
        on_fallback=fallback_messages.append,
    )

    response = service.transcribe(
        b"audio",
        content_type="audio/wav",
        filename="command.wav",
    )

    assert response.text == "local text"
    assert cloud.calls
    assert local.calls
    assert fallback_messages == [
        "OpenAI transcription is unavailable; using local transcription."
    ]


def test_openai_transcription_service_uses_sdk_request_and_removes_temp_file() -> None:
    fake_transcriptions = FakeOpenAITranscriptions(FakeTranscript("open calculator"))
    service = OpenAITranscriptionService(
        api_key_getter=lambda name: "test-key",
        client_factory=lambda api_key: FakeOpenAIClient(fake_transcriptions),
    )

    response = service.transcribe(
        b"audio",
        content_type="audio/wav",
        filename="command.wav",
    )

    assert response.text == "open calculator"
    assert response.language == "en"
    assert fake_transcriptions.file_path is not None
    assert not os.path.exists(fake_transcriptions.file_path)
    assert fake_transcriptions.calls[0]["model"] == "gpt-transcribe"
    assert fake_transcriptions.calls[0]["language"] == "en"
    assert "DeskPilot" in str(fake_transcriptions.calls[0]["prompt"])


def test_openai_transcription_service_removes_temp_file_on_failure() -> None:
    fake_transcriptions = FakeOpenAITranscriptions(
        FakeTranscript("open calculator"),
        fail=True,
    )
    service = OpenAITranscriptionService(
        api_key_getter=lambda name: "test-key",
        client_factory=lambda api_key: FakeOpenAIClient(fake_transcriptions),
    )

    try:
        service.transcribe(
            b"audio",
            content_type="audio/wav",
            filename="command.wav",
        )
    except TranscriptionServiceError as error:
        assert str(error) == "OpenAI transcription is unavailable."
    else:
        raise AssertionError("Expected TranscriptionServiceError")

    assert fake_transcriptions.file_path is not None
    assert not os.path.exists(fake_transcriptions.file_path)
