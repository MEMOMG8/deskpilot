from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from deskpilot_backend.main import app, get_process_launcher, get_speech_engine_factory


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
def mocked_dependencies(
    launcher: RecordingLauncher | None = None,
    speech_engine_factory: object | None = None,
) -> Iterator[None]:
    if launcher is not None:
        app.dependency_overrides[get_process_launcher] = lambda: launcher

    if speech_engine_factory is not None:
        app.dependency_overrides[get_speech_engine_factory] = (
            lambda: speech_engine_factory
        )

    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_assistant_open_calculator_routes_and_executes_successfully() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open calculator"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_app",
        "status": "executed",
        "requires_confirmation": False,
        "message": "Calculator was recognized and launch was requested.",
        "speech_result": "not_requested",
        "action": {"type": "open_app", "target": "calculator"},
    }


def test_assistant_process_launcher_is_mocked_for_calculator() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        client.post(
            "/api/v1/assistant/commands",
            json={"text": "open calculator"},
        )

    assert launcher.commands == [["calc.exe"]]


def test_assistant_help_does_not_call_executor() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post("/api/v1/assistant/commands", json={"text": "help"})

    assert response.status_code == 200
    assert response.json() == {
        "intent": "help",
        "status": "completed",
        "requires_confirmation": False,
        "message": 'Supported commands: "open calculator" and "help".',
        "speech_result": "not_requested",
    }
    assert launcher.commands == []


def test_assistant_unknown_command_does_not_call_executor() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open notepad"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "unknown",
        "status": "not_supported",
        "requires_confirmation": False,
        "message": "That command is not supported yet.",
        "speech_result": "not_requested",
    }
    assert launcher.commands == []


def test_assistant_blank_input_is_rejected() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/assistant/commands", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Value error, text must not be empty"


def test_assistant_speak_omitted_or_false_does_not_call_speech_service() -> None:
    client = TestClient(app)

    def speech_service_must_not_run() -> FakeSpeechEngine:
        raise AssertionError("speech service should not run")

    with mocked_dependencies(speech_engine_factory=speech_service_must_not_run):
        omitted_response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "help"},
        )
        false_response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "help", "speak": False},
        )

    assert omitted_response.status_code == 200
    assert omitted_response.json()["speech_result"] == "not_requested"
    assert false_response.status_code == 200
    assert false_response.json()["speech_result"] == "not_requested"


def test_assistant_open_calculator_with_speak_executes_and_narrates() -> None:
    launcher = RecordingLauncher()
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher, speech_engine_factory=lambda: engine):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open calculator", "speak": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_app",
        "status": "executed",
        "requires_confirmation": False,
        "message": "Calculator was recognized and launch was requested.",
        "speech_result": "completed",
        "action": {"type": "open_app", "target": "calculator"},
    }
    assert launcher.commands == [["calc.exe"]]
    assert engine.spoken_text == ["Calculator was recognized and launch was requested."]
    assert engine.completed is True


def test_assistant_help_with_speak_narrates_without_executing_app() -> None:
    launcher = RecordingLauncher()
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher, speech_engine_factory=lambda: engine):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "help", "speak": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "help",
        "status": "completed",
        "requires_confirmation": False,
        "message": 'Supported commands: "open calculator" and "help".',
        "speech_result": "completed",
    }
    assert launcher.commands == []
    assert engine.spoken_text == ['Supported commands: "open calculator" and "help".']


def test_assistant_speech_failure_does_not_change_command_result() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    def unavailable_speech_engine() -> FakeSpeechEngine:
        raise RuntimeError("speech unavailable")

    with mocked_dependencies(
        launcher=launcher,
        speech_engine_factory=unavailable_speech_engine,
    ):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open calculator", "speak": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_app",
        "status": "executed",
        "requires_confirmation": False,
        "message": "Calculator was recognized and launch was requested.",
        "speech_result": "unavailable",
        "action": {"type": "open_app", "target": "calculator"},
    }
    assert launcher.commands == [["calc.exe"]]
