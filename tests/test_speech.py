from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from deskpilot_backend.main import app, get_speech_engine_factory
from deskpilot_backend.speech import SpeechEngineError, speak_text


class FakeSpeechEngine:
    def __init__(self) -> None:
        self.spoken_text: list[str] = []
        self.completed = False

    def say(self, text: str) -> None:
        self.spoken_text.append(text)

    def runAndWait(self) -> None:
        self.completed = True


@contextmanager
def mocked_speech_engine(engine: FakeSpeechEngine) -> Iterator[None]:
    app.dependency_overrides[get_speech_engine_factory] = lambda: lambda: engine
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_speak_text_uses_engine_without_real_audio() -> None:
    engine = FakeSpeechEngine()

    response = speak_text("Hello Manuel, DeskPilot is ready.", engine_factory=lambda: engine)

    assert response.status == "completed"
    assert response.message == "Speech completed."
    assert engine.spoken_text == ["Hello Manuel, DeskPilot is ready."]
    assert engine.completed is True


def test_speech_endpoint_speaks_successfully_with_mocked_engine() -> None:
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_speech_engine(engine):
        response = client.post(
            "/api/v1/speech/speak",
            json={"text": "Hello Manuel, DeskPilot is ready."},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "completed", "message": "Speech completed."}
    assert engine.spoken_text == ["Hello Manuel, DeskPilot is ready."]


def test_speech_endpoint_rejects_blank_input() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/speech/speak", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Value error, text must not be empty"


def test_speak_text_raises_controlled_error_when_engine_is_unavailable() -> None:
    def unavailable_engine() -> FakeSpeechEngine:
        raise RuntimeError("driver unavailable")

    try:
        speak_text("hello", engine_factory=unavailable_engine)
    except SpeechEngineError as error:
        assert str(error) == "Local speech engine is unavailable."
    else:
        raise AssertionError("Expected SpeechEngineError")


def test_speech_endpoint_returns_controlled_error_when_engine_is_unavailable() -> None:
    client = TestClient(app)

    def unavailable_engine() -> FakeSpeechEngine:
        raise RuntimeError("driver unavailable")

    app.dependency_overrides[get_speech_engine_factory] = lambda: unavailable_engine
    try:
        response = client.post("/api/v1/speech/speak", json={"text": "hello"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json() == {"detail": "Local speech engine is unavailable."}
