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


def test_calculator_action_is_allowed() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_app", target="calculator")

    response = execute_action(action, launcher=launcher)

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action


def test_process_launcher_is_called_with_only_fixed_calculator_command() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_app", target="calculator")

    execute_action(action, launcher=launcher)

    assert launcher.commands == [["calc.exe"]]


def test_unsupported_target_is_rejected_and_never_launches_process() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_app", target="notepad")

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
        json={"type": "open_app", "target": "notepad"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported action target: notepad"}
