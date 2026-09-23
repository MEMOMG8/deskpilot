from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from deskpilot_backend.main import app, get_process_launcher


class RecordingLauncher:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> object:
        self.commands.append(command)
        return object()


@contextmanager
def mocked_launcher(launcher: RecordingLauncher) -> Iterator[None]:
    app.dependency_overrides[get_process_launcher] = lambda: launcher
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_assistant_open_calculator_routes_and_executes_successfully() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_launcher(launcher):
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
        "action": {"type": "open_app", "target": "calculator"},
    }


def test_assistant_process_launcher_is_mocked_for_calculator() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_launcher(launcher):
        client.post(
            "/api/v1/assistant/commands",
            json={"text": "open calculator"},
        )

    assert launcher.commands == [["calc.exe"]]


def test_assistant_help_does_not_call_executor() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_launcher(launcher):
        response = client.post("/api/v1/assistant/commands", json={"text": "help"})

    assert response.status_code == 200
    assert response.json() == {
        "intent": "help",
        "status": "completed",
        "requires_confirmation": False,
        "message": 'Supported commands: "open calculator" and "help".',
    }
    assert launcher.commands == []


def test_assistant_unknown_command_does_not_call_executor() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_launcher(launcher):
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
    }
    assert launcher.commands == []


def test_assistant_blank_input_is_rejected() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/assistant/commands", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Value error, text must not be empty"
