import os
import tempfile
from collections.abc import Callable, Iterable
from typing import Literal
from typing import Protocol

from deskpilot_backend.models import TranscriptionResponse

DEFAULT_WHISPER_MODEL = "tiny.en"
DEFAULT_TRANSCRIPTION_PROVIDER = "auto"
OPENAI_TRANSCRIPTION_MODEL = "gpt-transcribe"
OPENAI_TRANSCRIPTION_HINT = (
    "DeskPilot command vocabulary includes DeskPilot, Jarvis, GitHub, YouTube, "
    "Notepad, File Explorer, Calculator, settings, reminders, notes, media "
    "controls, and Windows workspace shortcuts."
)
TranscriptionProvider = Literal["auto", "local", "openai"]
ApiKeyGetter = Callable[[str], str | None]
OpenAIClientFactory = Callable[[str], object]
FallbackNotifier = Callable[[str], None]
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


class TranscriptionService(Protocol):
    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str | None,
        filename: str | None = None,
    ) -> TranscriptionResponse:
        """Transcribe audio bytes into command text."""


class EmptyAudioError(ValueError):
    """Raised when an uploaded audio file has no bytes."""


class UnsupportedAudioError(ValueError):
    """Raised when an uploaded file is not a supported audio type."""


class TranscriptionServiceError(RuntimeError):
    """Raised when transcription cannot complete safely."""


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


class OpenAITranscriptionService:
    def __init__(
        self,
        *,
        model_name: str = OPENAI_TRANSCRIPTION_MODEL,
        api_key_getter: ApiKeyGetter | None = None,
        client_factory: OpenAIClientFactory | None = None,
    ) -> None:
        self.model_name = model_name
        self._api_key_getter = api_key_getter or os.getenv
        self._client_factory = client_factory or _default_openai_client_factory

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
            client = self._create_client()
            with open(temp_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=self.model_name,
                    file=audio_file,
                    language="en",
                    prompt=OPENAI_TRANSCRIPTION_HINT,
                )

            text = _transcript_text(transcript)
            language = _transcript_language(transcript)
        except TranscriptionServiceError:
            raise
        except Exception as error:
            raise TranscriptionServiceError(
                "OpenAI transcription is unavailable."
            ) from error
        finally:
            os.unlink(temp_path)

        return TranscriptionResponse(
            status="completed",
            message="Transcription completed.",
            text=text,
            language=language,
        )

    def _create_client(self) -> object:
        api_key = self._api_key_getter("OPENAI_API_KEY")
        if not isinstance(api_key, str) or not api_key.strip():
            raise TranscriptionServiceError(
                "OpenAI transcription requires OPENAI_API_KEY."
            )

        return self._client_factory(api_key.strip())


class ProviderTranscriptionService:
    def __init__(
        self,
        *,
        provider: TranscriptionProvider = DEFAULT_TRANSCRIPTION_PROVIDER,
        local_service: TranscriptionService | None = None,
        openai_service: TranscriptionService | None = None,
        api_key_getter: ApiKeyGetter | None = None,
        on_fallback: FallbackNotifier | None = None,
    ) -> None:
        self.provider = provider
        self.local_service = local_service or WhisperTranscriptionService()
        self._api_key_getter = api_key_getter or os.getenv
        self.openai_service = openai_service or OpenAITranscriptionService(
            api_key_getter=self._api_key_getter
        )
        self.on_fallback = on_fallback

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str | None,
        filename: str | None = None,
    ) -> TranscriptionResponse:
        if self.provider == "local":
            return self.local_service.transcribe(
                audio_bytes,
                content_type=content_type,
                filename=filename,
            )

        if not self._openai_api_key_available():
            if self.provider == "openai":
                self._notify_fallback(
                    "OpenAI transcription is not configured; using local transcription."
                )
            return self._transcribe_with_local(audio_bytes, content_type, filename)

        try:
            return self.openai_service.transcribe(
                audio_bytes,
                content_type=content_type,
                filename=filename,
            )
        except TranscriptionServiceError as error:
            self._notify_fallback(
                "OpenAI transcription is unavailable; using local transcription."
            )
            try:
                return self._transcribe_with_local(audio_bytes, content_type, filename)
            except TranscriptionServiceError as local_error:
                raise TranscriptionServiceError(
                    "OpenAI transcription is unavailable and local fallback failed."
                ) from local_error

    def _transcribe_with_local(
        self,
        audio_bytes: bytes,
        content_type: str | None,
        filename: str | None,
    ) -> TranscriptionResponse:
        return self.local_service.transcribe(
            audio_bytes,
            content_type=content_type,
            filename=filename,
        )

    def _openai_api_key_available(self) -> bool:
        api_key = self._api_key_getter("OPENAI_API_KEY")
        return isinstance(api_key, str) and bool(api_key.strip())

    def _notify_fallback(self, message: str) -> None:
        if self.on_fallback is not None:
            self.on_fallback(message)


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


def _default_openai_client_factory(api_key: str) -> object:
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _transcript_text(transcript: object) -> str:
    if isinstance(transcript, dict):
        value = transcript.get("text")
    else:
        value = getattr(transcript, "text", None)

    return value if isinstance(value, str) else ""


def _transcript_language(transcript: object) -> str | None:
    if isinstance(transcript, dict):
        value = transcript.get("language")
    else:
        value = getattr(transcript, "language", None)

    return value if isinstance(value, str) else None
