import pytest
from fastapi.testclient import TestClient

from deskpilot_backend.actions import (
    KEYEVENTF_KEYUP,
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MEDIA_PREV_TRACK,
    VK_VOLUME_DOWN,
    VK_VOLUME_MUTE,
    VK_VOLUME_UP,
    UnsupportedActionError,
    execute_action,
)
from deskpilot_backend.main import app, get_key_event_sender
from deskpilot_backend.models import ActionExecutionRequest


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


@pytest.mark.parametrize(
    ("target", "expected_command", "expected_message"),
    [
        ("calculator", ["calc.exe"], "Opening Calculator."),
        ("notepad", ["notepad.exe"], "Opening Notepad."),
        ("file_explorer", ["explorer.exe"], "Opening File Explorer."),
        ("settings", ["explorer.exe", "ms-settings:"], "Opening Windows Settings."),
        (
            "browser",
            ["rundll32.exe", "url.dll,FileProtocolHandler", "https://example.com"],
            "Opening your default browser.",
        ),
    ],
)
def test_open_app_actions_are_allowed_with_fixed_commands(
    target: str,
    expected_command: list[str],
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_app", target=target)

    response = execute_action(action, launcher=launcher)

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert launcher.commands == [expected_command]


@pytest.mark.parametrize(
    ("target", "virtual_key", "expected_message"),
    [
        ("volume_up", VK_VOLUME_UP, "Turning volume up."),
        ("volume_down", VK_VOLUME_DOWN, "Turning volume down."),
        ("mute", VK_VOLUME_MUTE, "Toggling mute."),
        ("play_pause", VK_MEDIA_PLAY_PAUSE, "Toggling media playback."),
        ("next_track", VK_MEDIA_NEXT_TRACK, "Skipping to the next track."),
        ("previous_track", VK_MEDIA_PREV_TRACK, "Going to the previous track."),
    ],
)
def test_media_key_actions_are_allowed_with_fixed_key_events(
    target: str,
    virtual_key: int,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    key_event_sender = RecordingKeyEventSender()
    action = ActionExecutionRequest(type="media_key", target=target)

    response = execute_action(
        action,
        launcher=launcher,
        key_event_sender=key_event_sender,
    )

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert launcher.commands == []
    assert key_event_sender.events == [(virtual_key, 0), (virtual_key, KEYEVENTF_KEYUP)]


def test_media_key_rejects_unsupported_platform_without_succeeding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("deskpilot_backend.actions.sys.platform", "linux")
    action = ActionExecutionRequest(type="media_key", target="volume_up")

    with pytest.raises(
        UnsupportedActionError,
        match="Windows media controls are only supported on Windows.",
    ):
        execute_action(action)


def test_unsupported_target_is_rejected_and_never_launches_process() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_app", target="paint")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_unsupported_media_target_is_rejected_and_never_sends_key_event() -> None:
    key_event_sender = RecordingKeyEventSender()
    action = ActionExecutionRequest(type="media_key", target="stop_music")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, key_event_sender=key_event_sender)

    assert key_event_sender.events == []


def test_unsupported_action_type_is_rejected_and_never_launches_process() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="delete_file", target="calculator")

    with pytest.raises(UnsupportedActionError, match="Unsupported action type"):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_actions_execute_endpoint_rejects_unsupported_action() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/actions/execute",
        json={"type": "open_app", "target": "paint"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported action target: paint"}


def test_actions_execute_endpoint_uses_mocked_media_key_sender() -> None:
    key_event_sender = RecordingKeyEventSender()
    client = TestClient(app)
    app.dependency_overrides[get_key_event_sender] = lambda: key_event_sender

    try:
        response = client.post(
            "/api/v1/actions/execute",
            json={"type": "media_key", "target": "mute"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Toggling mute."
    assert key_event_sender.events == [(VK_VOLUME_MUTE, 0), (VK_VOLUME_MUTE, KEYEVENTF_KEYUP)]
