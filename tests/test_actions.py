import pytest
from fastapi.testclient import TestClient

from deskpilot_backend.actions import UnsupportedActionError, execute_action
from deskpilot_backend.main import app
from deskpilot_backend.models import ActionExecutionRequest


class RecordingLauncher:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> object:
        self.commands.append(command)
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


def test_unsupported_target_is_rejected_and_never_launches_process() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_app", target="paint")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


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
