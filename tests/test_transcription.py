import io
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from deskpilot_backend.main import app, get_transcription_service
from deskpilot_backend.models import TranscriptionResponse
from deskpilot_backend.transcription import (
    EmptyAudioError,
    TranscriptionServiceError,
    UnsupportedAudioError,
    validate_audio_upload,
)


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
