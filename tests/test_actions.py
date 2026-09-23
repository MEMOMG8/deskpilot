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
    format_battery_status,
    format_disk_status,
    format_memory_status,
)
from deskpilot_backend.main import app, get_key_event_sender, get_system_status_reader
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


class RecordingSystemStatusReader:
    def __init__(self, messages: dict[str, str]) -> None:
        self.messages = messages
        self.targets: list[str] = []

    def __call__(self, target: str) -> str:
        self.targets.append(target)
        return self.messages[target]


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


@pytest.mark.parametrize(
    ("target", "expected_command", "expected_message"),
    [
        ("downloads", ["explorer.exe"], "Opening Downloads."),
        ("documents", ["explorer.exe"], "Opening Documents."),
        ("desktop", ["explorer.exe"], "Opening Desktop."),
        ("task_manager", ["taskmgr.exe"], "Opening Task Manager."),
    ],
)
def test_workspace_shortcuts_are_allowed_with_fixed_targets(
    target: str,
    expected_command: list[str],
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="workspace_shortcut", target=target)

    response = execute_action(action, launcher=launcher)

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert launcher.commands[0][0:1] == expected_command
    if target != "task_manager":
        assert len(launcher.commands[0]) == 2


@pytest.mark.parametrize(
    ("target", "expected_message"),
    [
        ("battery", "Battery is at 82%."),
        ("memory", "Memory usage is 47%."),
        ("disk", "Disk space is 123.4 GB available of 476.8 GB on C:."),
    ],
)
def test_system_status_actions_are_allowed_with_read_only_reader(
    target: str,
    expected_message: str,
) -> None:
    reader = RecordingSystemStatusReader(
        {
            "battery": "Battery is at 82%.",
            "memory": "Memory usage is 47%.",
            "disk": "Disk space is 123.4 GB available of 476.8 GB on C:.",
        }
    )
    launcher = RecordingLauncher()
    key_event_sender = RecordingKeyEventSender()
    action = ActionExecutionRequest(type="system_status", target=target)

    response = execute_action(
        action,
        launcher=launcher,
        key_event_sender=key_event_sender,
        system_status_reader=reader,
    )

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert reader.targets == [target]
    assert launcher.commands == []
    assert key_event_sender.events == []


def test_status_formatters_return_concise_spoken_values() -> None:
    assert format_battery_status(82) == "Battery is at 82%."
    assert format_battery_status(None) == "No battery detected."
    assert format_memory_status(47) == "Memory usage is 47%."
    assert (
        format_disk_status(123.44, 476.82, "C:")
        == "Disk space is 123.4 GB available of 476.8 GB on C:."
    )


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


def test_workspace_shortcut_rejects_unsupported_platform_without_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("deskpilot_backend.actions.sys.platform", "linux")
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="workspace_shortcut", target="downloads")

    with pytest.raises(
        UnsupportedActionError,
        match="Workspace shortcuts are only supported on Windows.",
    ):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_system_status_rejects_unsupported_platform_without_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("deskpilot_backend.actions.sys.platform", "linux")
    reader = RecordingSystemStatusReader({"battery": "Battery is at 82%."})
    action = ActionExecutionRequest(type="system_status", target="battery")

    with pytest.raises(
        UnsupportedActionError,
        match="System status commands are only supported on Windows.",
    ):
        execute_action(action, system_status_reader=reader)

    assert reader.targets == []


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


def test_unsupported_workspace_target_is_rejected_and_never_launches_process() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="workspace_shortcut", target="pictures")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_unsupported_status_target_is_rejected_and_never_reads_status() -> None:
    reader = RecordingSystemStatusReader({"cpu": "CPU usage is 5%."})
    action = ActionExecutionRequest(type="system_status", target="cpu")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, system_status_reader=reader)

    assert reader.targets == []


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


def test_actions_execute_endpoint_uses_mocked_system_status_reader() -> None:
    reader = RecordingSystemStatusReader({"battery": "No battery detected."})
    client = TestClient(app)
    app.dependency_overrides[get_system_status_reader] = lambda: reader

    try:
        response = client.post(
            "/api/v1/actions/execute",
            json={"type": "system_status", "target": "battery"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "No battery detected."
    assert reader.targets == ["battery"]
