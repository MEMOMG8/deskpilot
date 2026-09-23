import os
import tempfile
from collections.abc import Iterable
from typing import Protocol

from deskpilot_backend.models import TranscriptionResponse

DEFAULT_WHISPER_MODEL = "tiny.en"
SUPPORTED_AUDIO_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
    "application/ogg",
    "video/mp4",
    "video/webm",
}


class TranscriptionSegment(Protocol):
    text: str


class TranscriptionInfo(Protocol):
    language: str | None


class EmptyAudioError(ValueError):
    """Raised when an uploaded audio file has no bytes."""


class UnsupportedAudioError(ValueError):
    """Raised when an uploaded file is not a supported audio type."""


class TranscriptionServiceError(RuntimeError):
    """Raised when local transcription cannot complete safely."""


def validate_audio_upload(content_type: str | None, audio_bytes: bytes) -> None:
    if not audio_bytes:
        raise EmptyAudioError("Uploaded audio file is empty.")

    if content_type not in SUPPORTED_AUDIO_CONTENT_TYPES:
        raise UnsupportedAudioError("Unsupported audio upload type.")


class WhisperTranscriptionService:
    def __init__(self, model_name: str = DEFAULT_WHISPER_MODEL) -> None:
        self.model_name = model_name
        self._model: object | None = None

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str | None,
        filename: str | None = None,
    ) -> TranscriptionResponse:
        validate_audio_upload(content_type, audio_bytes)
        suffix = _suffix_for_filename(filename)
        temp_path = _write_temp_audio_file(audio_bytes, suffix)

        try:
            segments, info = self._get_model().transcribe(temp_path)
            text = _join_segments(segments)
            language = getattr(info, "language", None)
        except Exception as error:
            raise TranscriptionServiceError("Local transcription is unavailable.") from error
        finally:
            os.unlink(temp_path)

        return TranscriptionResponse(
            status="completed",
            message="Transcription completed.",
            text=text,
            language=language,
        )

    def _get_model(self) -> object:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
            )
        return self._model


def _join_segments(segments: Iterable[TranscriptionSegment]) -> str:
    return " ".join(segment.text.strip() for segment in segments).strip()


def _suffix_for_filename(filename: str | None) -> str:
    if not filename:
        return ".audio"

    _, extension = os.path.splitext(filename)
    return extension or ".audio"


def _write_temp_audio_file(audio_bytes: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(audio_bytes)
        return temp_file.name
