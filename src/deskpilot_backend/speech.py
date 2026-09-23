from collections.abc import Callable
from typing import Protocol

from deskpilot_backend.models import SpeechResponse


class SpeechEngine(Protocol):
    def say(self, text: str) -> None:
        ...

    def runAndWait(self) -> None:
        ...


SpeechEngineFactory = Callable[[], SpeechEngine]


class SpeechEngineError(RuntimeError):
    """Raised when local text-to-speech cannot complete safely."""


def _create_sapi_engine() -> SpeechEngine:
    import pyttsx3

    return pyttsx3.init(driverName="sapi5")


def speak_text(
    text: str,
    engine_factory: SpeechEngineFactory | None = None,
) -> SpeechResponse:
    try:
        engine = (engine_factory or _create_sapi_engine)()
    except Exception as error:
        raise SpeechEngineError("Local speech engine is unavailable.") from error

    try:
        engine.say(text)
        engine.runAndWait()
    except Exception as error:
        raise SpeechEngineError("Local speech engine could not speak the text.") from error

    return SpeechResponse(status="completed", message="Speech completed.")
