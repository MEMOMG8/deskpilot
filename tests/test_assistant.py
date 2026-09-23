from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from deskpilot_backend.actions import KEYEVENTF_KEYUP, VK_MEDIA_PLAY_PAUSE, VK_VOLUME_UP
from deskpilot_backend.commands import HELP_MESSAGE
from deskpilot_backend.main import (
    app,
    get_key_event_sender,
    get_process_launcher,
    get_speech_engine_factory,
)


class RecordingLauncher:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> object:
        self.commands.append(command)
        return object()


class RecordingKeyEventSender:
    def __init__(self) -> None:
        self.events: list[tuple[int, int]] = []

    def __call__(self, virtual_key: int, flags: int) -> object:
        self.events.append((virtual_key, flags))
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
    key_event_sender: RecordingKeyEventSender | None = None,
    speech_engine_factory: object | None = None,
) -> Iterator[None]:
    if launcher is not None:
        app.dependency_overrides[get_process_launcher] = lambda: launcher

    if key_event_sender is not None:
        app.dependency_overrides[get_key_event_sender] = lambda: key_event_sender

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
        "message": "Opening Calculator.",
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


@pytest.mark.parametrize(
    ("text", "target", "expected_command", "expected_message"),
    [
        ("open notepad", "notepad", ["notepad.exe"], "Opening Notepad."),
        ("open file explorer", "file_explorer", ["explorer.exe"], "Opening File Explorer."),
        ("open explorer", "file_explorer", ["explorer.exe"], "Opening File Explorer."),
        ("open settings", "settings", ["explorer.exe", "ms-settings:"], "Opening Windows Settings."),
        (
            "open browser",
            "browser",
            ["rundll32.exe", "url.dll,FileProtocolHandler", "https://example.com"],
            "Opening your default browser.",
        ),
    ],
)
def test_assistant_app_commands_route_and_execute(
    text: str,
    target: str,
    expected_command: list[str],
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_app",
        "status": "executed",
        "requires_confirmation": False,
        "message": expected_message,
        "speech_result": "not_requested",
        "action": {"type": "open_app", "target": target},
    }
    assert launcher.commands == [expected_command]


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
        "message": HELP_MESSAGE,
        "speech_result": "not_requested",
    }
    assert launcher.commands == []


def test_assistant_unknown_command_does_not_call_executor() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open paint"},
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


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("what time is it", "get_time"),
        ("what's the time", "get_time"),
        ("what is the date", "get_date"),
        ("what's today's date", "get_date"),
        ("what can you do", "help"),
    ],
)
def test_assistant_information_commands_do_not_call_executor(
    text: str,
    intent: str,
) -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json()["intent"] == intent
    assert response.json()["status"] == "completed"
    assert launcher.commands == []


@pytest.mark.parametrize(
    ("text", "target", "virtual_key", "expected_message"),
    [
        ("volume up", "volume_up", VK_VOLUME_UP, "Turning volume up."),
        ("turn volume up", "volume_up", VK_VOLUME_UP, "Turning volume up."),
        ("play music", "play_pause", VK_MEDIA_PLAY_PAUSE, "Toggling media playback."),
        ("pause music", "play_pause", VK_MEDIA_PLAY_PAUSE, "Toggling media playback."),
    ],
)
def test_assistant_media_commands_route_and_send_fixed_key_events(
    text: str,
    target: str,
    virtual_key: int,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    key_event_sender = RecordingKeyEventSender()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher, key_event_sender=key_event_sender):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "media_control",
        "status": "executed",
        "requires_confirmation": False,
        "message": expected_message,
        "speech_result": "not_requested",
        "action": {"type": "media_key", "target": target},
    }
    assert launcher.commands == []
    assert key_event_sender.events == [(virtual_key, 0), (virtual_key, KEYEVENTF_KEYUP)]


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
        "message": "Opening Calculator.",
        "speech_result": "completed",
        "action": {"type": "open_app", "target": "calculator"},
    }
    assert launcher.commands == [["calc.exe"]]
    assert engine.spoken_text == ["Opening Calculator."]
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
        "message": HELP_MESSAGE,
        "speech_result": "completed",
    }
    assert launcher.commands == []
    assert engine.spoken_text == [HELP_MESSAGE]


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
        "message": "Opening Calculator.",
        "speech_result": "unavailable",
        "action": {"type": "open_app", "target": "calculator"},
    }
    assert launcher.commands == [["calc.exe"]]
